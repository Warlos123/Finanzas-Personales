import imaplib
import re
from email.message import EmailMessage

import pytest

from conftest import leer_fixture
from finanzas import db, gmail

COMANDOS_PERMITIDOS = ("LOGIN", "LIST", "EXAMINE ", "UID SEARCH ", "UID FETCH ", "LOGOUT")


def _correo(nombre_fixture: str, fecha: str = "Mon, 26 Oct 2026 14:43:48 +0000") -> bytes:
    """Correo como lo entrega Gmail: HTML quoted-printable con imágenes inline."""
    mensaje = EmailMessage()
    mensaje["From"] = gmail.REMITENTE
    mensaje["To"] = "yo@example.com"
    mensaje["Subject"] = "Notificación de Transacciones BCR"
    mensaje["Date"] = fecha
    mensaje.set_content(leer_fixture("bcr/" + nombre_fixture), subtype="html", cte="quoted-printable")
    mensaje.add_related(b"\x89PNG falso", "image", "png", cid="<vLogo>")
    return mensaje.as_bytes()


class ImapFalso:
    """Imita las respuestas de imaplib y registra cada comando enviado."""

    def __init__(self, mensajes, uidvalidity="1", rechazar_login=False):
        self.mensajes = mensajes
        self.uidvalidity = uidvalidity
        self.rechazar_login = rechazar_login
        self.comandos = []

    def login(self, usuario, contrasena):
        self.comandos.append("LOGIN")
        if self.rechazar_login:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"autenticado"]

    def list(self):
        self.comandos.append("LIST")
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
        ]

    def select(self, carpeta, readonly=False):
        assert readonly is True
        self.comandos.append("EXAMINE " + carpeta)
        return "OK", [str(len(self.mensajes)).encode()]

    def response(self, codigo):
        assert codigo == "UIDVALIDITY"
        return codigo, [self.uidvalidity.encode()]

    def uid(self, comando, *args):
        self.comandos.append("UID " + comando + " " + " ".join(args))
        if comando == "SEARCH":
            uids = sorted(self.mensajes)
            rango = re.search(r"UID (\d+):\*", " ".join(args))
            if rango is not None:
                minimo = int(rango.group(1))
                filtrados = []
                for i in range(len(uids)):
                    if uids[i] >= minimo:
                        filtrados.append(uids[i])
                # Semántica real de "n:*": incluye el último mensaje aunque sea menor que n.
                if not filtrados and uids:
                    filtrados = [uids[-1]]
                uids = filtrados
            texto = []
            for i in range(len(uids)):
                texto.append(str(uids[i]))
            return "OK", [" ".join(texto).encode()]
        if comando == "FETCH":
            assert args[1] == "(BODY.PEEK[])"
            crudo = self.mensajes[int(args[0])]
            return "OK", [(f"1 (UID {args[0]} BODY[] {{{len(crudo)}}}".encode(), crudo), b")"]
        raise AssertionError("Comando IMAP no permitido: " + comando)

    def logout(self):
        self.comandos.append("LOGOUT")
        return "BYE", [b"adios"]


@pytest.fixture
def configurado(conn, monkeypatch):
    with conn:
        db.guardar_ajuste(conn, gmail.AJUSTE_USUARIO, "yo@example.com")
    monkeypatch.setattr(gmail, "leer_contrasena", lambda usuario: "clave")
    notificaciones = []
    monkeypatch.setattr(gmail, "notificar", lambda *args, **kwargs: notificaciones.append(args))
    return notificaciones


def _contar(conn, tabla):
    return conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


def _comandos_de(imap, prefijo):
    encontrados = []
    for i in range(len(imap.comandos)):
        if imap.comandos[i].startswith(prefijo):
            encontrados.append(imap.comandos[i])
    return encontrados


def test_backfill_importa_y_guarda_ultimo_uid(conn, configurado):
    imap = ImapFalso({3: _correo("una_fila.html"), 7: _correo("varias_filas.html")})

    resumen = gmail.importar_gmail(conn, abrir_imap=lambda: imap)

    assert (resumen.nuevos, resumen.duplicados, resumen.errores) == (2, 0, 0)
    assert _contar(conn, "transactions") == 4
    assert db.leer_ajuste(conn, 'imap_ultimo_uid:"[Gmail]/All Mail"') == "7"
    busqueda = _comandos_de(imap, "UID SEARCH")[0]
    assert "SINCE" in busqueda
    assert f'FROM "{gmail.REMITENTE}"' in busqueda


def test_solo_comandos_de_lectura(conn, configurado):
    imap = ImapFalso({3: _correo("una_fila.html")})
    gmail.importar_gmail(conn, abrir_imap=lambda: imap)

    for i in range(len(imap.comandos)):
        assert imap.comandos[i].startswith(COMANDOS_PERMITIDOS), imap.comandos[i]
    assert 'EXAMINE "[Gmail]/All Mail"' in imap.comandos


def test_segunda_corrida_solo_pide_lo_nuevo(conn, configurado):
    mensajes = {3: _correo("una_fila.html")}
    gmail.importar_gmail(conn, abrir_imap=lambda: ImapFalso(mensajes))

    sin_novedades = ImapFalso(mensajes)
    resumen = gmail.importar_gmail(conn, abrir_imap=lambda: sin_novedades)
    assert resumen.nuevos == 0
    assert _comandos_de(sin_novedades, "UID FETCH") == []
    assert "UID 4:*" in _comandos_de(sin_novedades, "UID SEARCH")[0]

    mensajes[9] = _correo("varias_filas.html")
    con_nuevo = ImapFalso(mensajes)
    resumen = gmail.importar_gmail(conn, abrir_imap=lambda: con_nuevo)
    assert resumen.nuevos == 1
    assert len(_comandos_de(con_nuevo, "UID FETCH")) == 1
    assert _contar(conn, "transactions") == 4


def test_cambio_de_uidvalidity_reimporta_sin_duplicar(conn, configurado):
    mensajes = {3: _correo("una_fila.html")}
    gmail.importar_gmail(conn, abrir_imap=lambda: ImapFalso(mensajes, uidvalidity="1"))

    resumen = gmail.importar_gmail(conn, abrir_imap=lambda: ImapFalso(mensajes, uidvalidity="2"))

    assert resumen.duplicados == 1
    assert _contar(conn, "raw_events") == 1
    assert _contar(conn, "transactions") == 1


def test_credenciales_invalidas_avisa_una_vez_y_no_reintenta(conn, configurado):
    rechazo = ImapFalso({}, rechazar_login=True)
    with pytest.raises(gmail.ErrorCredenciales):
        gmail.importar_gmail(conn, abrir_imap=lambda: rechazo)
    assert len(configurado) == 1
    assert db.leer_ajuste(conn, gmail.AJUSTE_CREDENCIALES_INVALIDAS) is not None

    def no_conectar():
        raise AssertionError("No debe conectarse con credenciales marcadas como inválidas")

    with pytest.raises(gmail.ErrorCredenciales):
        gmail.importar_gmail(conn, abrir_imap=no_conectar)
    assert len(configurado) == 1


def test_sin_configurar_es_error(conn):
    with pytest.raises(gmail.ErrorConfiguracion):
        gmail.importar_gmail(conn, abrir_imap=lambda: ImapFalso({}))


def test_registra_import_runs(conn, configurado):
    gmail.importar_gmail(conn, abrir_imap=lambda: ImapFalso({3: _correo("una_fila.html")}))
    corrida = conn.execute("SELECT fuente, fin, nuevos, errores FROM import_runs").fetchone()
    assert corrida["fuente"] == "gmail_bcr"
    assert corrida["fin"] is not None
    assert corrida["nuevos"] == 1
    assert corrida["errores"] == 0


def test_extraer_html_decodifica_y_convierte_fecha():
    html, recibido_en = gmail.extraer_html(_correo("una_fila.html"))
    assert "Detalle de Transacciones" in html
    assert "Autorización" in html
    assert recibido_en == "2026-10-26T08:43:48-06:00"


def test_fecha_imap_sin_locale():
    from datetime import date

    assert gmail.fecha_imap(date(2026, 5, 3)) == "03-May-2026"


def test_configurar_guarda_usuario_y_limpia_marca(conn, monkeypatch):
    guardadas = []
    monkeypatch.setattr(gmail, "guardar_contrasena", lambda u, c: guardadas.append((u, c)))
    with conn:
        db.guardar_ajuste(conn, gmail.AJUSTE_CREDENCIALES_INVALIDAS, "2026-10-01")

    gmail.configurar(conn, "yo@example.com", "clave", abrir_imap=lambda: ImapFalso({}))

    assert guardadas == [("yo@example.com", "clave")]
    assert db.leer_ajuste(conn, gmail.AJUSTE_USUARIO) == "yo@example.com"
    assert db.leer_ajuste(conn, gmail.AJUSTE_CREDENCIALES_INVALIDAS) is None


def test_configurar_con_clave_mala_no_guarda_nada(conn, monkeypatch):
    guardadas = []
    monkeypatch.setattr(gmail, "guardar_contrasena", lambda u, c: guardadas.append((u, c)))
    with pytest.raises(gmail.ErrorCredenciales):
        gmail.configurar(conn, "yo@example.com", "mala", abrir_imap=lambda: ImapFalso({}, rechazar_login=True))
    assert guardadas == []
    assert db.leer_ajuste(conn, gmail.AJUSTE_USUARIO) is None
