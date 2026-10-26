"""Conexión a SQLite (modo WAL) y migraciones numeradas."""

import sqlite3
from pathlib import Path

DIR_MIGRACIONES = Path(__file__).parent / "migrations"


def conectar(ruta) -> sqlite3.Connection:
    """Abre la base, activa WAL y llaves foráneas, y aplica migraciones pendientes."""
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    migrar(conn)
    return conn


def _migraciones() -> list[tuple[int, Path]]:
    """Archivos `NNNN_nombre.sql` ordenados por número."""
    archivos = sorted(DIR_MIGRACIONES.glob("*.sql"))
    lista = []
    for i in range(len(archivos)):
        numero = int(archivos[i].name.split("_", 1)[0])
        lista.append((numero, archivos[i]))
    return lista


def migrar(conn: sqlite3.Connection) -> int:
    """Aplica en orden las migraciones con número mayor a `user_version`. Devuelve la versión final."""
    actual = conn.execute("PRAGMA user_version").fetchone()[0]
    migraciones = _migraciones()
    for i in range(len(migraciones)):
        numero, ruta = migraciones[i]
        if numero <= actual:
            continue
        sql = ruta.read_text(encoding="utf-8")
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {numero};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        actual = numero
    return actual
