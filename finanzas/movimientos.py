"""Consultas y cambios sobre transacciones usados por la UI. Ninguna función hace commit."""

import sqlite3
from dataclasses import dataclass

from finanzas.formato import rango_mes
from finanzas.tiempo import ahora_iso

TIPOS = ("gasto", "ingreso", "transferencia", "reembolsable")
ESTADOS = ("confirmada", "pendiente", "ignorada")
MONEDAS = ("CRC", "USD")

_SELECT = """
SELECT t.*, a.nombre AS cuenta_nombre, a.tipo AS cuenta_tipo, c.nombre AS categoria_nombre
FROM transactions t
LEFT JOIN accounts a ON a.id = t.cuenta_id
LEFT JOIN categories c ON c.id = t.categoria_id
"""

# Pendiente de revisar: moneda desconocida, o gasto sin categoría. Las ignoradas no cuentan.
_CONDICION_BANDEJA = (
    "t.estado != 'ignorada' AND (t.estado = 'pendiente' OR (t.categoria_id IS NULL AND t.tipo = 'gasto'))"
)


@dataclass
class Filtros:
    mes: str | None = None
    cuenta_id: int | None = None
    categoria: str | None = None  # id como texto, o "sin" para las que no tienen
    tipo: str | None = None
    texto: str | None = None
    incluir_ignoradas: bool = False


def listar(conn: sqlite3.Connection, filtros: Filtros, limite: int = 1000) -> list:
    condiciones = []
    parametros = []
    if filtros.mes:
        inicio, fin = rango_mes(filtros.mes)
        condiciones.append("t.fecha_hora >= ? AND t.fecha_hora < ?")
        parametros.extend([inicio, fin])
    if filtros.cuenta_id is not None:
        condiciones.append("t.cuenta_id = ?")
        parametros.append(filtros.cuenta_id)
    if filtros.categoria == "sin":
        condiciones.append("t.categoria_id IS NULL")
    elif filtros.categoria:
        condiciones.append("t.categoria_id = ?")
        parametros.append(int(filtros.categoria))
    if filtros.tipo:
        condiciones.append("t.tipo = ?")
        parametros.append(filtros.tipo)
    if filtros.texto:
        condiciones.append(
            "(t.comercio_o_destinatario LIKE ? OR t.descripcion LIKE ? OR t.notas LIKE ?)"
        )
        patron = "%" + filtros.texto + "%"
        parametros.extend([patron, patron, patron])
    if not filtros.incluir_ignoradas:
        condiciones.append("t.estado != 'ignorada'")
    sql = _SELECT
    if condiciones:
        sql = sql + " WHERE " + " AND ".join(condiciones)
    sql = sql + " ORDER BY t.fecha_hora DESC, t.id DESC LIMIT ?"
    parametros.append(limite)
    return conn.execute(sql, parametros).fetchall()


def obtener(conn: sqlite3.Connection, transaccion_id: int):
    return conn.execute(_SELECT + " WHERE t.id = ?", (transaccion_id,)).fetchone()


def bandeja(conn: sqlite3.Connection, limite: int = 200) -> list:
    """Una fila por comercio/destinatario pendiente (la más reciente) con `iguales` = cuántas hay."""
    sql = f"""
    SELECT * FROM (
        SELECT t.*, a.nombre AS cuenta_nombre, a.tipo AS cuenta_tipo,
               COUNT(*) OVER (PARTITION BY t.comercio_o_destinatario) AS iguales,
               ROW_NUMBER() OVER (
                   PARTITION BY t.comercio_o_destinatario ORDER BY t.fecha_hora DESC, t.id DESC
               ) AS orden
        FROM transactions t LEFT JOIN accounts a ON a.id = t.cuenta_id
        WHERE {_CONDICION_BANDEJA}
    )
    WHERE orden = 1
    ORDER BY iguales DESC, fecha_hora DESC
    LIMIT ?
    """
    return conn.execute(sql, (limite,)).fetchall()


def contar_bandeja(conn: sqlite3.Connection) -> int:
    sql = "SELECT COUNT(*) FROM transactions t WHERE " + _CONDICION_BANDEJA
    return conn.execute(sql).fetchone()[0]


def errores_de_parseo(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT id, fuente, recibido_en, detalle_parseo FROM raw_events "
        "WHERE estado_parseo = 'error' ORDER BY recibido_en DESC"
    ).fetchall()


def categorizar(conn: sqlite3.Connection, transaccion_id: int, categoria_id: int | None, tipo: str) -> None:
    if tipo not in TIPOS:
        raise ValueError("Tipo inválido")
    conn.execute(
        "UPDATE transactions SET categoria_id = ?, tipo = ? WHERE id = ?",
        (categoria_id, tipo, transaccion_id),
    )


def ignorar(conn: sqlite3.Connection, transaccion_id: int) -> None:
    conn.execute("UPDATE transactions SET estado = 'ignorada' WHERE id = ?", (transaccion_id,))


@dataclass
class DatosTransaccion:
    fecha_hora: str
    monto_centimos: int
    moneda: str
    tipo: str
    cuenta_id: int | None
    categoria_id: int | None
    comercio_o_destinatario: str | None
    notas: str | None
    estado: str = "confirmada"
    extraordinario: bool = False


def _validar(datos: DatosTransaccion) -> None:
    if datos.tipo not in TIPOS:
        raise ValueError("Tipo inválido")
    if datos.estado not in ESTADOS:
        raise ValueError("Estado inválido")
    if datos.moneda not in MONEDAS:
        raise ValueError("Moneda inválida")
    if datos.monto_centimos < 0:
        raise ValueError("El monto no puede ser negativo")


def actualizar(conn: sqlite3.Connection, transaccion_id: int, datos: DatosTransaccion) -> None:
    """Edición manual: marca `editada_en`, así el reproceso no pisa estos valores."""
    _validar(datos)
    conn.execute(
        """UPDATE transactions SET fecha_hora = ?, monto_centimos = ?, moneda = ?, tipo = ?,
               cuenta_id = ?, categoria_id = ?, comercio_o_destinatario = ?, notas = ?,
               estado = ?, extraordinario = ?, editada_en = ?
           WHERE id = ?""",
        (
            datos.fecha_hora, datos.monto_centimos, datos.moneda, datos.tipo, datos.cuenta_id,
            datos.categoria_id, datos.comercio_o_destinatario, datos.notas, datos.estado,
            int(datos.extraordinario), ahora_iso(), transaccion_id,
        ),
    )


def crear_manual(conn: sqlite3.Connection, datos: DatosTransaccion) -> int:
    """Transacción sin evento crudo ni llave (p. ej. un ingreso por SINPE recibido)."""
    _validar(datos)
    cursor = conn.execute(
        """INSERT INTO transactions (fecha_hora, monto_centimos, moneda, tipo, cuenta_id,
               categoria_id, comercio_o_destinatario, notas, estado, extraordinario, creada_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datos.fecha_hora, datos.monto_centimos, datos.moneda, datos.tipo, datos.cuenta_id,
            datos.categoria_id, datos.comercio_o_destinatario, datos.notas, datos.estado,
            int(datos.extraordinario), ahora_iso(),
        ),
    )
    return cursor.lastrowid


def borrar(conn: sqlite3.Connection, transaccion_id: int) -> str:
    """Borra las manuales. Las generadas por un recurrente se ignoran (si no, se regenerarían).
    Las importadas no se borran: se ignoran desde la edición. Devuelve 'borrada' o 'ignorada'."""
    fila = obtener(conn, transaccion_id)
    if fila is None:
        raise ValueError("No existe la transacción")
    llave = fila["llave_unica"]
    if fila["raw_event_id"] is None and llave is None:
        conn.execute("DELETE FROM transactions WHERE id = ?", (transaccion_id,))
        return "borrada"
    if llave is not None and llave.startswith("recurrente:"):
        ignorar(conn, transaccion_id)
        return "ignorada"
    raise ValueError("Las transacciones importadas no se borran: márcala como ignorada")
