"""Línea de comandos: `finanzas [--db RUTA] <comando>`."""

import argparse
import getpass
import imaplib
import logging
import sys
from datetime import date
from pathlib import Path

from finanzas import db, gmail, ingesta
from finanzas.llavero import ErrorLlavero

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


def _cmd_importar(args) -> int:
    conn = _abrir_db(args)
    try:
        resumen = gmail.importar_gmail(conn, desde=args.desde)
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
    finally:
        conn.close()
    log.info(
        "Gmail: %d nuevos, %d duplicados, %d errores",
        resumen.nuevos, resumen.duplicados, resumen.errores,
    )
    return 0


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

    importar = comandos.add_parser("importar", help="importar correos BCR nuevos")
    importar.add_argument(
        "--desde",
        type=date.fromisoformat,
        help=f"recorrer desde esta fecha (AAAA-MM-DD); sin estado previo: últimos {gmail.DIAS_BACKFILL} días",
    )
    importar.set_defaults(funcion=_cmd_importar)

    reprocesar = comandos.add_parser("reprocesar", help="volver a parsear todos los eventos crudos")
    reprocesar.add_argument("--fuente", choices=["gmail_bcr", "sms_4066"])
    reprocesar.set_defaults(funcion=_cmd_reprocesar)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.funcion(args)
