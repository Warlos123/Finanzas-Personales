"""Contraseña de aplicación de Gmail en el llavero del sistema (libsecret vía `secret-tool`).

La contraseña viaja por stdin, nunca como argumento (no aparece en la lista de procesos),
y no se escribe en archivos, variables de entorno ni logs.
"""

import subprocess

_ATRIBUTOS = ["service", "finanzas-gmail", "usuario"]


class ErrorLlavero(Exception):
    pass


def _ejecutar(comando: list[str], entrada: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(comando, input=entrada, text=True, capture_output=True, timeout=120)
    except FileNotFoundError:
        raise ErrorLlavero("No se encontró `secret-tool` (instala el paquete libsecret)") from None
    except subprocess.TimeoutExpired:
        raise ErrorLlavero("El llavero no respondió (¿está bloqueado?)") from None


def guardar_contrasena(usuario: str, contrasena: str) -> None:
    comando = ["secret-tool", "store", "--label=Finanzas: Gmail IMAP"] + _ATRIBUTOS + [usuario]
    resultado = _ejecutar(comando, contrasena)
    if resultado.returncode != 0:
        raise ErrorLlavero("secret-tool no pudo guardar la contraseña")


def leer_contrasena(usuario: str) -> str | None:
    """Devuelve la contraseña o None si no está guardada."""
    resultado = _ejecutar(["secret-tool", "lookup"] + _ATRIBUTOS + [usuario])
    contrasena = resultado.stdout.strip()
    if resultado.returncode != 0 or contrasena == "":
        return None
    return contrasena
