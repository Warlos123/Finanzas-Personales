"""Ingresos recurrentes: generan un ingreso por mes (editable) en su `dia_del_mes`.

Cada ingreso generado lleva la llave `recurrente:<id>:<AAAA-MM>`, así generar de nuevo
no duplica, y una edición manual o un "borrado" (queda ignorado) se respetan.
"""

import calendar
import sqlite3
from datetime import date, datetime

from finanzas.tiempo import ZONA_CR, ahora_iso


def generar(conn: sqlite3.Connection, hoy: date) -> int:
    """Crea los ingresos de los recurrentes activos cuya fecha ya llegó. Devuelve cuántos creó.
    No hace commit."""
    recurrentes = conn.execute("SELECT * FROM recurring_incomes WHERE activa = 1").fetchall()
    creados = 0
    for i in range(len(recurrentes)):
        recurrente = recurrentes[i]
        desde = date(hoy.year, hoy.month, 1)
        if recurrente["desde"]:
            desde = date.fromisoformat(recurrente["desde"])
        anio = desde.year
        mes = desde.month
        while (anio, mes) <= (hoy.year, hoy.month):
            dia = min(recurrente["dia_del_mes"], calendar.monthrange(anio, mes)[1])
            fecha = date(anio, mes, dia)
            if desde <= fecha <= hoy:
                creados += _crear_ingreso(conn, recurrente, fecha)
            mes += 1
            if mes == 13:
                mes = 1
                anio += 1
    return creados


def _crear_ingreso(conn: sqlite3.Connection, recurrente, fecha: date) -> int:
    fecha_hora = datetime(fecha.year, fecha.month, fecha.day, tzinfo=ZONA_CR).isoformat()
    llave = f"recurrente:{recurrente['id']}:{fecha.year:04d}-{fecha.month:02d}"
    cursor = conn.execute(
        """INSERT INTO transactions (fecha_hora, monto_centimos, moneda, tipo, cuenta_id,
               comercio_o_destinatario, estado, llave_unica, creada_en)
           VALUES (?, ?, ?, 'ingreso', ?, ?, 'confirmada', ?, ?)
           ON CONFLICT (llave_unica) DO NOTHING""",
        (
            fecha_hora, recurrente["monto_centimos"], recurrente["moneda"], recurrente["cuenta_id"],
            recurrente["nombre"], llave, ahora_iso(),
        ),
    )
    return cursor.rowcount


def guardar(
    conn: sqlite3.Connection,
    recurrente_id: int | None,
    nombre: str,
    monto_centimos: int,
    moneda: str,
    dia_del_mes: int,
    cuenta_id: int | None,
    activa: bool,
    desde: str | None,
) -> int:
    """Crea (id None) o actualiza un recurrente. No hace commit."""
    nombre = nombre.strip()
    if nombre == "":
        raise ValueError("El nombre no puede estar vacío")
    if dia_del_mes < 1 or dia_del_mes > 31:
        raise ValueError("El día del mes debe estar entre 1 y 31")
    if moneda not in ("CRC", "USD"):
        raise ValueError("Moneda inválida")
    valores = (nombre, monto_centimos, moneda, dia_del_mes, cuenta_id, int(activa), desde)
    if recurrente_id is None:
        cursor = conn.execute(
            "INSERT INTO recurring_incomes (nombre, monto_centimos, moneda, dia_del_mes, cuenta_id, "
            "activa, desde) VALUES (?, ?, ?, ?, ?, ?, ?)",
            valores,
        )
        return cursor.lastrowid
    conn.execute(
        "UPDATE recurring_incomes SET nombre = ?, monto_centimos = ?, moneda = ?, dia_del_mes = ?, "
        "cuenta_id = ?, activa = ?, desde = ? WHERE id = ?",
        valores + (recurrente_id,),
    )
    return recurrente_id


def borrar(conn: sqlite3.Connection, recurrente_id: int) -> None:
    """Borra la definición; los ingresos ya generados se quedan."""
    conn.execute("DELETE FROM recurring_incomes WHERE id = ?", (recurrente_id,))
