import pytest

from finanzas import catalogos, reglas


def test_cuentas_crear_editar_y_validar(conn):
    cuenta = catalogos.guardar_cuenta(conn, None, "Efectivo", "efectivo", "", "CRC")
    catalogos.guardar_cuenta(conn, cuenta, "Billetera", "efectivo", None, "USD")
    fila = conn.execute("SELECT * FROM accounts WHERE id = ?", (cuenta,)).fetchone()
    assert (fila["nombre"], fila["ultimos4"], fila["moneda"]) == ("Billetera", None, "USD")
    with pytest.raises(ValueError):
        catalogos.guardar_cuenta(conn, None, "X", "tarjeta", "12a4", "CRC")


def test_categorias_jerarquia_y_borrado(conn):
    comida = conn.execute("SELECT id FROM categories WHERE nombre = 'Comida'").fetchone()["id"]
    cafe = catalogos.guardar_categoria(conn, None, "Café", comida)
    nombres = []
    filas = catalogos.categorias(conn)
    for i in range(len(filas)):
        nombres.append(filas[i]["nombre_completo"])
    assert "Comida / Café" in nombres

    conn.execute(
        "INSERT INTO transactions (fecha_hora, monto_centimos, moneda, tipo, categoria_id, creada_en) "
        "VALUES ('2026-10-01T00:00:00-06:00', 100, 'CRC', 'gasto', ?, 'x')",
        (comida,),
    )
    reglas.crear_regla(conn, "comercio", "SODA", comida)
    reglas.crear_regla(conn, "comercio", "PAGO", comida, tipo_forzado="transferencia")

    catalogos.borrar_categoria(conn, comida)

    assert conn.execute("SELECT categoria_id FROM transactions").fetchone()[0] is None
    restantes = conn.execute("SELECT patron, categoria_id FROM rules").fetchall()
    assert len(restantes) == 1
    assert (restantes[0]["patron"], restantes[0]["categoria_id"]) == ("PAGO", None)
    assert conn.execute("SELECT padre_id FROM categories WHERE id = ?", (cafe,)).fetchone()[0] is None
    with pytest.raises(ValueError):
        catalogos.guardar_categoria(conn, cafe, "Café", cafe)
