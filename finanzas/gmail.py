"""Importador de correos "Notificación de Transacciones BCR" por IMAP.

Estrictamente de solo lectura: la carpeta se abre con EXAMINE (`readonly=True`) y los
mensajes se leen con `BODY.PEEK[]`, que no los marca como leídos. Solo se usan los
comandos LOGIN, LIST, EXAMINE, UID SEARCH, UID FETCH y LOGOUT.

Se lee la carpeta "Todos" de Gmail (flag \\All) para incluir correos archivados. Se guarda
el último UID procesado por carpeta (válido mientras no cambie UIDVALIDITY); la
deduplicación de `ingesta` sigue siendo la garantía final.
"""

import email
import email.policy
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from finanzas import db, ingesta
from finanzas.llavero import guardar_contrasena, leer_contrasena
from finanzas.notificar import notificar
from finanzas.tiempo import ZONA_CR, ahora_iso

log = logging.getLogger(__name__)

SERVIDOR = "imap.gmail.com"
PUERTO = 993
REMITENTE = "bcrtarjestcta@bancobcr.com"
# Asunto real: "Notificación de Transacciones BCR". Se busca solo la palabra ASCII.
ASUNTO = "Transacciones"
FUENTE = "gmail_bcr"
DIAS_BACKFILL = 180

AJUSTE_USUARIO = "gmail_usuario"
AJUSTE_CREDENCIALES_INVALIDAS = "gmail_credenciales_invalidas"

_MESES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_PATRON_LIST = re.compile(r'^\((?P<banderas>[^)]*)\) (?:"[^"]*"|NIL) (?P<nombre>.+)$')


class ErrorConfiguracion(Exception):
    pass


class ErrorCredenciales(Exception):
    pass


@dataclass
class ResumenImportacion:
    nuevos: int = 0
    duplicados: int = 0
    errores: int = 0


def _abrir_imap():
    return imaplib.IMAP4_SSL(SERVIDOR, PUERTO, timeout=60)


def fecha_imap(dia: date) -> str:
    """Formato de fecha de IMAP (`26-Oct-2026`), sin depender del locale."""
    return f"{dia.day:02d}-{_MESES[dia.month - 1]}-{dia.year}"


def _verificar_ok(tipo: str, operacion: str) -> None:
    if tipo != "OK":
        raise imaplib.IMAP4.error(f"{operacion} respondió {tipo}")


def _cerrar(imap) -> None:
    try:
        imap.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def _carpeta_todos(imap) -> str:
    """Nombre (tal como lo da LIST) de la carpeta con flag \\All; si no hay, INBOX."""
    tipo, lineas = imap.list()
    if tipo != "OK":
        return "INBOX"
    for i in range(len(lineas)):
        if not isinstance(lineas[i], bytes):
            continue
        coincidencia = _PATRON_LIST.match(lineas[i].decode("utf-8", "replace"))
        if coincidencia is None:
            continue
        banderas = coincidencia.group("banderas").split()
        if "\\All" in banderas:
            return coincidencia.group("nombre")
    return "INBOX"


def _buscar_uids(imap, desde: date | None, ultimo_uid: int) -> list[int]:
    criterios = ["FROM", f'"{REMITENTE}"', "SUBJECT", f'"{ASUNTO}"']
    if desde is not None:
        criterios.extend(["SINCE", fecha_imap(desde)])
    if ultimo_uid > 0:
        criterios.extend(["UID", f"{ultimo_uid + 1}:*"])
    tipo, datos = imap.uid("SEARCH", *criterios)
    _verificar_ok(tipo, "SEARCH")
    partes = datos[0].split()
    uids = []
    for i in range(len(partes)):
        uid = int(partes[i])
        # "n:*" siempre incluye el último mensaje de la carpeta aunque su UID sea menor que n.
        if uid > ultimo_uid:
            uids.append(uid)
    uids.sort()
    return uids


def _descargar(imap, uid: int) -> bytes | None:
    tipo, datos = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
    _verificar_ok(tipo, "FETCH")
    for i in range(len(datos)):
        if isinstance(datos[i], tuple):
            return datos[i][1]
    return None


def extraer_html(crudo: bytes) -> tuple[str | None, str]:
    """Devuelve (html decodificado, fecha del encabezado Date en hora de CR)."""
    mensaje = email.message_from_bytes(crudo, policy=email.policy.default)
    cuerpo = mensaje.get_body(preferencelist=("html", "plain"))
    contenido = None
    if cuerpo is not None:
        contenido = cuerpo.get_content()

    recibido_en = ahora_iso()
    encabezado = mensaje["Date"]
    if encabezado is not None:
        try:
            fecha = parsedate_to_datetime(str(encabezado))
        except (TypeError, ValueError):
            fecha = None
        if fecha is not None and fecha.tzinfo is not None:
            recibido_en = fecha.astimezone(ZONA_CR).isoformat()
    return contenido, recibido_en


def _importar_carpeta(conn, imap, desde: date | None, resumen: ResumenImportacion) -> None:
    carpeta = _carpeta_todos(imap)
    tipo, _ = imap.select(carpeta, readonly=True)
    _verificar_ok(tipo, "EXAMINE")
    _, valores = imap.response("UIDVALIDITY")
    uidvalidity = ""
    if valores and valores[0] is not None:
        uidvalidity = valores[0].decode()

    clave_validez = f"imap_uidvalidity:{carpeta}"
    clave_uid = f"imap_ultimo_uid:{carpeta}"
    ultimo_uid = 0
    if uidvalidity != "" and db.leer_ajuste(conn, clave_validez) == uidvalidity:
        ultimo_uid = int(db.leer_ajuste(conn, clave_uid, "0"))

    # Con --desde se vuelve a recorrer desde esa fecha; sin estado guardado, backfill.
    uid_minimo = ultimo_uid
    if desde is not None:
        uid_minimo = 0
    elif ultimo_uid == 0:
        desde = datetime.now(ZONA_CR).date() - timedelta(days=DIAS_BACKFILL)

    uids = _buscar_uids(imap, desde, uid_minimo)
    log.info("Gmail: %d correos por revisar", len(uids))
    for i in range(len(uids)):
        uid = uids[i]
        crudo = _descargar(imap, uid)
        html = None
        recibido_en = ""
        if crudo is not None:
            html, recibido_en = extraer_html(crudo)
        if html is None:
            log.warning("Correo UID %d sin cuerpo legible", uid)
            resumen.errores += 1
        else:
            _, es_nuevo, proceso = ingesta.importar_evento(conn, FUENTE, html, recibido_en)
            if es_nuevo:
                resumen.nuevos += 1
            else:
                resumen.duplicados += 1
            if proceso.error:
                resumen.errores += 1
        if uid > ultimo_uid:
            ultimo_uid = uid
            with conn:
                db.guardar_ajuste(conn, clave_uid, ultimo_uid)
                db.guardar_ajuste(conn, clave_validez, uidvalidity)


def _registrar_inicio(conn) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO import_runs (fuente, inicio) VALUES (?, ?)", (FUENTE, ahora_iso())
        )
    return cursor.lastrowid


def _registrar_fin(conn, run_id: int, resumen: ResumenImportacion) -> None:
    with conn:
        conn.execute(
            "UPDATE import_runs SET fin = ?, nuevos = ?, duplicados = ?, errores = ? WHERE id = ?",
            (ahora_iso(), resumen.nuevos, resumen.duplicados, resumen.errores, run_id),
        )


def importar_gmail(conn, desde: date | None = None, abrir_imap=_abrir_imap) -> ResumenImportacion:
    """Importa correos nuevos (o desde `desde`). Si Gmail rechaza la contraseña, la marca
    como inválida, avisa una vez y no vuelve a conectarse hasta reconfigurar."""
    usuario = db.leer_ajuste(conn, AJUSTE_USUARIO)
    if usuario is None:
        raise ErrorConfiguracion("Gmail no está configurado: corre `finanzas configurar-gmail`")
    if db.leer_ajuste(conn, AJUSTE_CREDENCIALES_INVALIDAS) is not None:
        raise ErrorCredenciales(
            "La contraseña de aplicación fue rechazada antes: corre `finanzas configurar-gmail`"
        )
    contrasena = leer_contrasena(usuario)
    if contrasena is None:
        raise ErrorConfiguracion("No hay contraseña en el llavero: corre `finanzas configurar-gmail`")

    resumen = ResumenImportacion()
    run_id = _registrar_inicio(conn)
    try:
        imap = abrir_imap()
        try:
            try:
                imap.login(usuario, contrasena)
            except imaplib.IMAP4.error:
                with conn:
                    db.guardar_ajuste(conn, AJUSTE_CREDENCIALES_INVALIDAS, ahora_iso())
                notificar(
                    "Finanzas: Gmail rechazó la contraseña",
                    "La importación de correos BCR está detenida. Corre `finanzas configurar-gmail`.",
                    urgente=True,
                )
                raise ErrorCredenciales("Gmail rechazó la contraseña de aplicación") from None
            _importar_carpeta(conn, imap, desde, resumen)
        finally:
            _cerrar(imap)
    except Exception:
        resumen.errores += 1
        raise
    finally:
        _registrar_fin(conn, run_id, resumen)
    return resumen


def configurar(conn, usuario: str, contrasena: str, abrir_imap=_abrir_imap) -> None:
    """Prueba el login; si funciona, guarda la contraseña en el llavero y el usuario en settings."""
    imap = abrir_imap()
    try:
        imap.login(usuario, contrasena)
    except imaplib.IMAP4.error:
        raise ErrorCredenciales("Gmail rechazó el usuario o la contraseña de aplicación") from None
    finally:
        _cerrar(imap)
    guardar_contrasena(usuario, contrasena)
    with conn:
        db.guardar_ajuste(conn, AJUSTE_USUARIO, usuario)
        db.guardar_ajuste(conn, AJUSTE_CREDENCIALES_INVALIDAS, None)
