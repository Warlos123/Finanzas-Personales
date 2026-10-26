"""Zona horaria y marcas de tiempo."""

from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_CR = ZoneInfo("America/Costa_Rica")


def ahora_iso() -> str:
    """Fecha y hora actual en Costa Rica, ISO 8601 con offset."""
    return datetime.now(ZONA_CR).isoformat(timespec="seconds")
