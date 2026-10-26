"""Reglas de categorización.

Una regla compara su `patron` (sin tildes ni mayúsculas, "contiene") con:
- `comercio`: comercio de transacciones que no son SINPE,
- `destinatario`: destinatario de transacciones SINPE,
- `descripcion`: descripción (p. ej. "Almuerzo" en un SINPE).

Se evalúan por `prioridad` ascendente (y luego por id); gana la primera que coincide.
Solo se aplican a transacciones sin categoría, sin edición manual y no ignoradas.
"""

import sqlite3

from finanzas.parsers.base import normalizar

CAMPOS = ("comercio", "destinatario", "descripcion")

_SQL_CANDIDATAS = """
SELECT t.id, t.tipo, t.categoria_id, t.comercio_o_destinatario, t.descripcion,
       a.tipo AS cuenta_tipo
FROM transactions t LEFT JOIN accounts a ON a.id = t.cuenta_id
WHERE t.categoria_id IS NULL AND t.editada_en IS NULL AND t.estado != 'ignorada'
"""


def campo_principal(cuenta_tipo: str | None) -> str:
    """Campo con el que se identifica una transacción: destinatario en SINPE, comercio en el resto."""
    if cuenta_tipo == "sinpe":
        return "destinatario"
    return "comercio"


def _texto_del_campo(campo: str, transaccion) -> str | None:
    if campo == "descripcion":
        return transaccion["descripcion"]
    if campo == campo_principal(transaccion["cuenta_tipo"]):
        return transaccion["comercio_o_destinatario"]
    return None


def buscar_regla(reglas: list, transaccion):
    """Primera regla (ya ordenada por prioridad) que coincide con la transacción, o None."""
    for i in range(len(reglas)):
        texto = _texto_del_campo(reglas[i]["campo"], transaccion)
        if texto is None:
            continue
        if normalizar(reglas[i]["patron"]) in normalizar(texto):
            return reglas[i]
    return None


def aplicar_reglas(conn: sqlite3.Connection, transaccion_ids: list[int] | None = None) -> int:
    """Aplica reglas a las transacciones candidatas (todas o solo `transaccion_ids`).
    Devuelve cuántas cambiaron. No hace commit."""
    reglas = conn.execute("SELECT * FROM rules ORDER BY prioridad, id").fetchall()
    if not reglas:
        return 0
    candidatas = []
    if transaccion_ids is None:
        candidatas = conn.execute(_SQL_CANDIDATAS).fetchall()
    else:
        for i in range(len(transaccion_ids)):
            fila = conn.execute(_SQL_CANDIDATAS + " AND t.id = ?", (transaccion_ids[i],)).fetchone()
            if fila is not None:
                candidatas.append(fila)

    cambiadas = 0
    for i in range(len(candidatas)):
        transaccion = candidatas[i]
        regla = buscar_regla(reglas, transaccion)
        if regla is None:
            continue
        categoria_id = transaccion["categoria_id"]
        if regla["categoria_id"] is not None:
            categoria_id = regla["categoria_id"]
        tipo = transaccion["tipo"]
        if regla["tipo_forzado"] is not None:
            tipo = regla["tipo_forzado"]
        if categoria_id == transaccion["categoria_id"] and tipo == transaccion["tipo"]:
            continue
        conn.execute(
            "UPDATE transactions SET categoria_id = ?, tipo = ? WHERE id = ?",
            (categoria_id, tipo, transaccion["id"]),
        )
        cambiadas += 1
    return cambiadas


def crear_regla(
    conn: sqlite3.Connection,
    campo: str,
    patron: str,
    categoria_id: int | None,
    tipo_forzado: str | None = None,
    prioridad: int | None = None,
) -> int:
    """Crea una regla al final del orden (si no se da prioridad). No hace commit."""
    patron = patron.strip()
    if campo not in CAMPOS:
        raise ValueError("Campo de regla inválido")
    if patron == "":
        raise ValueError("El patrón no puede estar vacío")
    if categoria_id is None and tipo_forzado is None:
        raise ValueError("La regla necesita una categoría o un tipo")
    if prioridad is None:
        maxima = conn.execute("SELECT MAX(prioridad) FROM rules").fetchone()[0]
        prioridad = 10
        if maxima is not None:
            prioridad = maxima + 10
    cursor = conn.execute(
        "INSERT INTO rules (campo, patron, categoria_id, tipo_forzado, prioridad) VALUES (?, ?, ?, ?, ?)",
        (campo, patron, categoria_id, tipo_forzado, prioridad),
    )
    return cursor.lastrowid
