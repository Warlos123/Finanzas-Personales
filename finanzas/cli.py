"""Línea de comandos: `finanzas [--db RUTA] <comando>`."""

import argparse
import getpass
import imaplib
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from finanzas import alertas, db, gmail, ingesta, respaldos, resumen, telefono
from finanzas.llavero import ErrorLlavero
from finanzas.tiempo import ZONA_CR, ahora_iso

log = logging.getLogger("finanzas")


def _abrir_db(args):
    ruta = Path(args.db)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return db.conectar(ruta)


def _cmd_configurar_gmail(args) -> int:
    contrasena = getpass.getpass("Contraseña de aplicación de Gmail (no se muestra): ")
    # Google la muestra en bloques de 4 separados por espacios.
    contrasena = "".join(contrasena.split())
    if contrasena == "":
        print("Error: contraseña vacía", file=sys.stderr)
        return 1
    conn = _abrir_db(args)
    try:
        gmail.configurar(conn, args.usuario, contrasena)
    except gmail.ErrorCredenciales as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except ErrorLlavero as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except OSError:
        print(f"Error: no se pudo conectar a {gmail.SERVIDOR}", file=sys.stderr)
        return 3
    finally:
        conn.close()
    print("Listo: credenciales verificadas y guardadas en el llavero del sistema.")
    return 0


def _cmd_configurar_telefono(args) -> int:
    conn = _abrir_db(args)
    try:
        agregados = telefono.configurar(conn, Path(args.carpeta))
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Listo: se importarán los eventos de {Path(args.carpeta).expanduser().resolve()}")
    if agregados:
        print("Agregado a .stignore de Syncthing: " + ", ".join(agregados))
    return 0


def _importar_telefono(conn) -> int:
    """0 si salió bien o el teléfono no está configurado; 4 si la carpeta no existe."""
    try:
        resumen = telefono.importar_telefono(conn)
    except FileNotFoundError as error:
        log.error("%s", error)
        return 4
    if resumen is not None and (resumen.nuevos or resumen.duplicados or resumen.rechazados):
        log.info(
            "Teléfono: %d nuevos, %d duplicados, %d rechazados, %d errores",
            resumen.nuevos, resumen.duplicados, resumen.rechazados, resumen.errores,
        )
    return 0


def _importar_gmail(conn, desde) -> int:
    try:
        resumen = gmail.importar_gmail(conn, desde=desde)
    except gmail.ErrorConfiguracion as error:
        log.error("%s", error)
        return 1
    except gmail.ErrorCredenciales as error:
        log.error("%s", error)
        return 2
    except ErrorLlavero as error:
        log.error("%s", error)
        return 1
    except (OSError, imaplib.IMAP4.error) as error:
        log.error("Falló la conexión con Gmail (%s): %s", type(error).__name__, error)
        return 3
    log.info(
        "Gmail: %d nuevos, %d duplicados, %d errores",
        resumen.nuevos, resumen.duplicados, resumen.errores,
    )
    return 0


def _tareas_posteriores(conn, ruta_db, antes, inicio: str) -> None:
    """Alertas, backup diario y resumen mensual. Si una falla, las demás igual corren."""
    ahora = datetime.now(ZONA_CR)
    tareas = (
        ("aviso de novedades", lambda: alertas.avisar_novedades(conn, antes)),
        ("aviso del teléfono", lambda: alertas.avisar_telefono(conn, ahora)),
        ("aviso de presupuestos", lambda: alertas.avisar_presupuestos(conn, ahora.date())),
        ("aviso de gasto atípico", lambda: alertas.avisar_atipicos(conn, inicio)),
        ("backup diario", lambda: respaldos.diario(conn, ruta_db, ahora.date())),
        ("resumen mensual", lambda: resumen.mensual(conn, ruta_db, ahora.date())),
    )
    for i in range(len(tareas)):
        nombre, tarea = tareas[i]
        try:
            tarea()
        except Exception as error:
            log.error("Falló %s (%s)", nombre, type(error).__name__)


def _cmd_importar(args) -> int:
    """Teléfono y Gmail son independientes: si uno falla, el otro igual se importa."""
    conn = _abrir_db(args)
    try:
        inicio = ahora_iso()
        antes = alertas.contar(conn)
        codigo_telefono = _importar_telefono(conn)
        codigo_gmail = _importar_gmail(conn, args.desde)
        _tareas_posteriores(conn, Path(args.db), antes, inicio)
    finally:
        conn.close()
    if codigo_gmail != 0:
        return codigo_gmail
    return codigo_telefono


def _cmd_reprocesar(args) -> int:
    conn = _abrir_db(args)
    try:
        resumen = ingesta.reprocesar(conn, args.fuente)
    finally:
        conn.close()
    print(f"Reprocesado: {resumen.nuevas} transacciones nuevas, {resumen.existentes} existentes")
    if resumen.error:
        print("Hay eventos con error de parseo (raw_events.estado_parseo = 'error').")
    return 0


def _cmd_ui(args) -> int:
    import uvicorn

    from finanzas.web.app import crear_app

    ruta = Path(args.db)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Siempre solo en 127.0.0.1: la UI no debe ser accesible desde la red.
    uvicorn.run(crear_app(ruta, args.puerto), host="127.0.0.1", port=args.puerto, log_level="warning")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="finanzas", description="Finanzas personales (local)")
    parser.add_argument(
        "--db", default=str(db.ruta_por_defecto()), help="ruta de la base SQLite (default: %(default)s)"
    )
    comandos = parser.add_subparsers(dest="comando", required=True)

    configurar = comandos.add_parser(
        "configurar-gmail", help="guardar la contraseña de aplicación en el llavero"
    )
    configurar.add_argument("usuario", help="dirección de Gmail")
    configurar.set_defaults(funcion=_cmd_configurar_gmail)

    configurar_telefono = comandos.add_parser(
        "configurar-telefono", help="carpeta de Syncthing donde el teléfono deja los eventos"
    )
    configurar_telefono.add_argument("carpeta")
    configurar_telefono.set_defaults(funcion=_cmd_configurar_telefono)

    importar = comandos.add_parser("importar", help="importar eventos del teléfono y correos BCR nuevos")
    importar.add_argument(
        "--desde",
        type=date.fromisoformat,
        help=f"recorrer desde esta fecha (AAAA-MM-DD); sin estado previo: últimos {gmail.DIAS_BACKFILL} días",
    )
    importar.set_defaults(funcion=_cmd_importar)

    reprocesar = comandos.add_parser("reprocesar", help="volver a parsear todos los eventos crudos")
    reprocesar.add_argument("--fuente", choices=["gmail_bcr", "sms_4066"])
    reprocesar.set_defaults(funcion=_cmd_reprocesar)

    ui = comandos.add_parser("ui", help="servir la UI web en http://127.0.0.1:PUERTO")
    ui.add_argument("--puerto", type=int, default=8765)
    ui.set_defaults(funcion=_cmd_ui)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.funcion(args)
