from datetime import date

import pytest

from finanzas import alertas, catalogos, formato, metricas, movimientos


def _categoria(conn, nombre):
    return conn.execute("SELECT id FROM categories WHERE nombre = ?", (nombre,)).fetchone()["id"]


def _gasto(conn, fecha, monto, categoria_id, moneda="CRC", tipo="gasto"):
    datos = movimientos.DatosTransaccion(
        fecha_hora=formato.fecha_desde_formulario(fecha), monto_centimos=monto, moneda=moneda,
        tipo=tipo, cuenta_id=None, categoria_id=categoria_id, comercio_o_destinatario="X", notas=None,
    )
    return movimientos.crear_manual(conn, datos)


@pytest.fixture
def avisos(monkeypatch):
    enviados = []
    monkeypatch.setattr(alertas, "notificar", lambda *args, **kwargs: enviados.append(args))
    return enviados


def test_guardar_y_quitar_presupuesto(conn):
    comida = _categoria(conn, "Comida")
    catalogos.guardar_presupuesto(conn, comida, 5000000)
    catalogos.guardar_presupuesto(conn, comida, 6000000)
    assert catalogos.presupuestos(conn) == {comida: 6000000}
    catalogos.guardar_presupuesto(conn, comida, None)
    assert catalogos.presupuestos(conn) == {}
    with pytest.raises(ValueError):
        catalogos.guardar_presupuesto(conn, comida, -1)


def test_estado_incluye_subcategorias_y_excluye_lo_que_no_es_gasto(conn):
    comida = _categoria(conn, "Comida")
    cafe = catalogos.guardar_categoria(conn, None, "Café", comida)
    catalogos.guardar_presupuesto(conn, comida, 10000000)
    _gasto(conn, "2026-10-02", 3000000, comida)
    _gasto(conn, "2026-10-03", 2000000, cafe)
    _gasto(conn, "2026-10-04", 9000000, comida, tipo="reembolsable")
    _gasto(conn, "2026-09-30", 9000000, comida)

    estado = metricas.estado_presupuestos(conn, "2026-10")

    assert len(estado) == 1
    assert (estado[0].nombre, estado[0].gastado, estado[0].presupuesto) == ("Comida", 5000000, 10000000)
    assert estado[0].proporcion == 0.5
    assert estado[0].nivel == "ok"


def test_avisa_al_80_y_al_100_una_vez_cada_uno(conn, avisos):
    transporte = _categoria(conn, "Transporte")
    catalogos.guardar_presupuesto(conn, transporte, 1000000)
    hoy = date(2026, 10, 20)

    _gasto(conn, "2026-10-01", 500000, transporte)
    assert alertas.avisar_presupuestos(conn, hoy) == 0

    _gasto(conn, "2026-10-05", 350000, transporte)
    assert alertas.avisar_presupuestos(conn, hoy) == 1
    assert "85%" in avisos[-1][1]
    assert alertas.avisar_presupuestos(conn, hoy) == 0

    _gasto(conn, "2026-10-06", 200000, transporte)
    assert alertas.avisar_presupuestos(conn, hoy) == 1
    assert "105%" in avisos[-1][1]
    assert alertas.avisar_presupuestos(conn, hoy) == 0
    assert len(avisos) == 2

    # Mes nuevo: se vuelve a avisar si se cruza otra vez.
    _gasto(conn, "2026-11-01", 900000, transporte)
    assert alertas.avisar_presupuestos(conn, date(2026, 11, 2)) == 1
