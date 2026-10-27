"""Cuentas y categorías. Ninguna función hace commit."""

import sqlite3

TIPOS_CUENTA = ("tarjeta", "sinpe", "efectivo", "otra")


def _nombre_valido(nombre: str) -> str:
    nombre = nombre.strip()
    if nombre == "":
        raise ValueError("El nombre no puede estar vacío")
    return nombre


def cuentas(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM accounts ORDER BY tipo, nombre").fetchall()


def guardar_cuenta(
    conn: sqlite3.Connection,
    cuenta_id: int | None,
    nombre: str,
    tipo: str,
    ultimos4: str | None,
    moneda: str,
) -> int:
    nombre = _nombre_valido(nombre)
    if tipo not in TIPOS_CUENTA:
        raise ValueError("Tipo de cuenta inválido")
    if moneda not in ("CRC", "USD"):
        raise ValueError("Moneda inválida")
    if ultimos4 is not None:
        ultimos4 = ultimos4.strip()
        if ultimos4 == "":
            ultimos4 = None
        elif len(ultimos4) != 4 or not ultimos4.isdigit():
            raise ValueError("Últimos 4 debe tener 4 dígitos")
    if cuenta_id is None:
        cursor = conn.execute(
            "INSERT INTO accounts (nombre, tipo, ultimos4, moneda) VALUES (?, ?, ?, ?)",
            (nombre, tipo, ultimos4, moneda),
        )
        return cursor.lastrowid
    conn.execute(
        "UPDATE accounts SET nombre = ?, tipo = ?, ultimos4 = ?, moneda = ? WHERE id = ?",
        (nombre, tipo, ultimos4, moneda, cuenta_id),
    )
    return cuenta_id


def categorias(conn: sqlite3.Connection) -> list:
    """Con `nombre_completo` = 'Padre / Hija' para mostrar."""
    return conn.execute(
        """SELECT c.*, CASE WHEN p.id IS NULL THEN c.nombre ELSE p.nombre || ' / ' || c.nombre END
                  AS nombre_completo
           FROM categories c LEFT JOIN categories p ON p.id = c.padre_id
           ORDER BY nombre_completo"""
    ).fetchall()


def guardar_categoria(
    conn: sqlite3.Connection, categoria_id: int | None, nombre: str, padre_id: int | None
) -> int:
    nombre = _nombre_valido(nombre)
    if categoria_id is not None and padre_id == categoria_id:
        raise ValueError("Una categoría no puede ser su propio padre")
    if categoria_id is None:
        cursor = conn.execute(
            "INSERT INTO categories (nombre, padre_id) VALUES (?, ?)", (nombre, padre_id)
        )
        return cursor.lastrowid
    conn.execute(
        "UPDATE categories SET nombre = ?, padre_id = ? WHERE id = ?", (nombre, padre_id, categoria_id)
    )
    return categoria_id


def borrar_categoria(conn: sqlite3.Connection, categoria_id: int) -> None:
    """Las transacciones quedan sin categoría (vuelven a la bandeja); las reglas que solo
    asignaban esa categoría se borran; las subcategorías quedan sin padre."""
    conn.execute("UPDATE transactions SET categoria_id = NULL WHERE categoria_id = ?", (categoria_id,))
    conn.execute(
        "DELETE FROM rules WHERE categoria_id = ? AND tipo_forzado IS NULL", (categoria_id,)
    )
    conn.execute("UPDATE rules SET categoria_id = NULL WHERE categoria_id = ?", (categoria_id,))
    conn.execute("DELETE FROM budgets WHERE categoria_id = ?", (categoria_id,))
    conn.execute("UPDATE categories SET padre_id = NULL WHERE padre_id = ?", (categoria_id,))
    conn.execute("DELETE FROM categories WHERE id = ?", (categoria_id,))


def presupuestos(conn: sqlite3.Connection) -> dict:
    """categoria_id -> monto mensual en céntimos (CRC)."""
    filas = conn.execute("SELECT categoria_id, monto_mensual_centimos FROM budgets").fetchall()
    resultado = {}
    for i in range(len(filas)):
        resultado[filas[i]["categoria_id"]] = filas[i]["monto_mensual_centimos"]
    return resultado


def guardar_presupuesto(conn: sqlite3.Connection, categoria_id: int, monto_centimos: int | None) -> None:
    """None o 0 quita el presupuesto."""
    if monto_centimos is None or monto_centimos == 0:
        conn.execute("DELETE FROM budgets WHERE categoria_id = ?", (categoria_id,))
        return
    if monto_centimos < 0:
        raise ValueError("El presupuesto no puede ser negativo")
    conn.execute(
        "INSERT INTO budgets (categoria_id, monto_mensual_centimos, moneda) VALUES (?, ?, 'CRC') "
        "ON CONFLICT (categoria_id) DO UPDATE SET monto_mensual_centimos = excluded.monto_mensual_centimos",
        (categoria_id, monto_centimos),
    )
