"""Notificaciones de escritorio con `notify-send`."""

import logging
import subprocess

log = logging.getLogger(__name__)


def notificar(titulo: str, cuerpo: str, urgente: bool = False) -> None:
    """Muestra una notificación. Si no se puede, solo deja un aviso en el log."""
    comando = ["notify-send", "--app-name=Finanzas"]
    if urgente:
        comando.append("--urgency=critical")
    comando.append(titulo)
    comando.append(cuerpo)
    try:
        subprocess.run(comando, capture_output=True, timeout=10, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.warning("No se pudo mostrar la notificación de escritorio")
