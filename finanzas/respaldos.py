"""Backup diario de la base con la API de respaldo de SQLite (consistente aunque haya WAL).

Archivos `backups/finanzas-AAAA-MM-DD.db` junto a la base; se conservan los últimos CONSERVAR.
"""

import os
import sqlite3
from datetime import date
from pathlib import Path

CONSERVAR = 14
PREFIJO = "finanzas-"


def carpeta_respaldos(ruta_db) -> Path:
    return Path(ruta_db).parent / "backups"


def respaldar(conn: sqlite3.Connection, destino: Path) -> None:
    """Copia la base a `destino` de forma atómica (primero a un temporal)."""
    destino.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    copia = sqlite3.connect(temporal)
    try:
        conn.backup(copia)
    finally:
        copia.close()
    os.replace(temporal, destino)


def rotar(carpeta: Path, conservar: int = CONSERVAR) -> int:
    """Borra los backups más viejos y deja `conservar`. Devuelve cuántos borró."""
    archivos = sorted(carpeta.glob(f"{PREFIJO}*.db"))  # la fecha ISO ordena cronológicamente
    sobran = len(archivos) - conservar
    for i in range(sobran):
        archivos[i].unlink()
    if sobran < 0:
        return 0
    return sobran


def diario(conn: sqlite3.Connection, ruta_db, hoy: date) -> Path | None:
    """Crea el backup del día si todavía no existe y rota. Devuelve la ruta creada o None."""
    carpeta = carpeta_respaldos(ruta_db)
    destino = carpeta / f"{PREFIJO}{hoy.isoformat()}.db"
    creado = None
    if not destino.exists():
        respaldar(conn, destino)
        creado = destino
    rotar(carpeta)
    return creado
