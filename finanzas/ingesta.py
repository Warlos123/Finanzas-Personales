"""Guardado idempotente de eventos crudos y de sus transacciones.

- Un evento crudo se identifica por (fuente, sha256 del contenido): reimportarlo no lo duplica.
- Una transacción se identifica por `llave_unica`: reprocesar hace upsert.
- El reproceso no pisa transacciones editadas a mano (`editada_en` no nulo) y nunca
  toca tipo, categoría ni notas; el estado solo cambia si estaba `pendiente`.
"""

import hashlib
import sqlite3
from dataclasses import dataclass

from finanzas.parsers import PARSERS
from finanzas.parsers.base import ErrorParseo, TransaccionParseada
from finanzas.tiempo import ahora_iso

_SQL_UPSERT = """
INSERT INTO transactions (
    raw_event_id, fecha_hora, monto_centimos, moneda, tipo, cuenta_id,
    comercio_o_destinatario, descripcion, estado, llave_unica, creada_en
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (llave_unica) DO UPDATE SET
    raw_event_id = excluded.raw_event_id,
    fecha_hora = excluded.fecha_hora,
    monto_centimos = excluded.monto_centimos,
    moneda = excluded.moneda,
    cuenta_id = excluded.cuenta_id,
    comercio_o_destinatario = excluded.comercio_o_destinatario,
    descripcion = excluded.descripcion,
    estado = CASE WHEN transactions.estado = 'pendiente' THEN excluded.estado ELSE transactions.estado END
WHERE transactions.editada_en IS NULL
"""


@dataclass
class ResumenProceso:
    nuevas: int = 0
    existentes: int = 0
    error: bool = False


def registrar_evento(conn: sqlite3.Connection, fuente: str, contenido: str, recibido_en: str):
    """Guarda el evento crudo. Devuelve (id, es_nuevo)."""
    huella = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
    cursor = conn.execute(
        "INSERT INTO raw_events (fuente, contenido, recibido_en, hash, creado_en) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (fuente, hash) DO NOTHING",
        (fuente, contenido, recibido_en, huella, ahora_iso()),
    )
    if cursor.rowcount == 1:
        return cursor.lastrowid, True
    fila = conn.execute(
        "SELECT id FROM raw_events WHERE fuente = ? AND hash = ?", (fuente, huella)
    ).fetchone()
    return fila["id"], False


def _cuenta_id(conn: sqlite3.Connection, tx: TransaccionParseada) -> int:
    """Busca la cuenta por tipo y últimos 4; si no existe la crea."""
    fila = conn.execute(
        "SELECT id FROM accounts WHERE tipo = ? AND ultimos4 IS ? ORDER BY id LIMIT 1",
        (tx.cuenta_tipo, tx.cuenta_ultimos4),
    ).fetchone()
    if fila is not None:
        return fila["id"]
    cursor = conn.execute(
        "INSERT INTO accounts (nombre, tipo, ultimos4) VALUES (?, ?, ?)",
        (tx.cuenta_nombre, tx.cuenta_tipo, tx.cuenta_ultimos4),
    )
    return cursor.lastrowid


def procesar_evento(conn: sqlite3.Connection, raw_event_id: int) -> ResumenProceso:
    """Parsea un evento crudo y hace upsert de sus transacciones. No hace commit."""
    evento = conn.execute(
        "SELECT fuente, contenido, recibido_en FROM raw_events WHERE id = ?", (raw_event_id,)
    ).fetchone()
    resumen = ResumenProceso()
    parser = PARSERS.get(evento["fuente"])
    try:
        if parser is None:
            raise ErrorParseo(f"Sin parser para la fuente '{evento['fuente']}'")
        resultado = parser(evento["contenido"], evento["recibido_en"])
    except ErrorParseo as error:
        conn.execute(
            "UPDATE raw_events SET estado_parseo = 'error', detalle_parseo = ?, procesado_en = ? "
            "WHERE id = ?",
            (str(error), ahora_iso(), raw_event_id),
        )
        resumen.error = True
        return resumen

    for i in range(len(resultado.transacciones)):
        tx = resultado.transacciones[i]
        existente = conn.execute(
            "SELECT id FROM transactions WHERE llave_unica = ?", (tx.llave_unica,)
        ).fetchone()
        conn.execute(
            _SQL_UPSERT,
            (
                raw_event_id, tx.fecha_hora, tx.monto_centimos, tx.moneda, tx.tipo,
                _cuenta_id(conn, tx), tx.comercio_o_destinatario, tx.descripcion,
                tx.estado, tx.llave_unica, ahora_iso(),
            ),
        )
        if existente is None:
            resumen.nuevas += 1
        else:
            resumen.existentes += 1

    estado = "ok"
    detalle = None
    if resultado.avisos:
        estado = "con_avisos"
        detalle = "\n".join(resultado.avisos)
    conn.execute(
        "UPDATE raw_events SET estado_parseo = ?, detalle_parseo = ?, procesado_en = ? WHERE id = ?",
        (estado, detalle, ahora_iso(), raw_event_id),
    )
    return resumen


def importar_evento(conn: sqlite3.Connection, fuente: str, contenido: str, recibido_en: str):
    """Registra y procesa un evento en una sola transacción de la base.
    Devuelve (raw_event_id, es_nuevo, resumen). Si ya existía, no lo reprocesa."""
    with conn:
        raw_event_id, es_nuevo = registrar_evento(conn, fuente, contenido, recibido_en)
        resumen = ResumenProceso()
        if es_nuevo:
            resumen = procesar_evento(conn, raw_event_id)
    return raw_event_id, es_nuevo, resumen


def reprocesar(conn: sqlite3.Connection, fuente: str | None = None) -> ResumenProceso:
    """Vuelve a parsear todos los eventos crudos (opcionalmente de una fuente)."""
    if fuente is None:
        filas = conn.execute("SELECT id FROM raw_events ORDER BY id").fetchall()
    else:
        filas = conn.execute(
            "SELECT id FROM raw_events WHERE fuente = ? ORDER BY id", (fuente,)
        ).fetchall()
    total = ResumenProceso()
    for i in range(len(filas)):
        with conn:
            resumen = procesar_evento(conn, filas[i]["id"])
        total.nuevas += resumen.nuevas
        total.existentes += resumen.existentes
        if resumen.error:
            total.error = True
    return total
