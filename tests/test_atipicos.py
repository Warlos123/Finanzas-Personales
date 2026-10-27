import pytest

from finanzas import alertas, formato, movimientos
from finanzas.tiempo import ahora_iso


def _categoria(conn, nombre):
    return conn.execute("SELECT id FROM categories WHERE nombre = ?", (nombre,)).fetchone()["id"]


def _cuenta(conn, tipo):
    return conn.execute("INSERT INTO accounts (nombre, tipo) VALUES ('C', ?)", (tipo,)).lastrowid


def _gasto(conn, fecha, monto, categoria_id=None, cuenta_id=None, nombre="SODA"):
    datos = movimientos.DatosTransaccion(
        fecha_hora=formato.fecha_desde_formulario(fecha), monto_centimos=monto, moneda="CRC",
        tipo="gasto", cuenta_id=cuenta_id, categoria_id=categoria_id, comercio_o_destinatario=nombre,
        notas=None,
    )
    return movimientos.crear_manual(conn, datos)


@pytest.fixture
def avisos(monkeypatch):
    enviados = []
    monkeypatch.setattr(alertas, "notificar", lambda *args, **kwargs: enviados.append(args))
    return enviados


@pytest.fixture
def historia(conn):
    """5 gastos de comida de ~₡5,000 en octubre, creados 'antes' de la corrida."""
    comida = _categoria(conn, "Comida")
    for i in range(5):
        _gasto(conn, f"2026-10-0{i + 1}", 500000 + i * 10000, comida)
    conn.execute("UPDATE transactions SET creada_en = '2000-01-01T00:00:00-06:00'")
    return comida


def test_detecta_gasto_mucho_mayor_que_lo_normal(conn, historia, avisos):
    desde = ahora_iso()
    _gasto(conn, "2026-10-20", 3000000, historia, nombre="RESTAURANTE CARO")
    _gasto(conn, "2026-10-21", 1800000, historia)  # 3.5× pero menor a ₡20,000

    assert alertas.avisar_atipicos(conn, desde) == 1
    assert "RESTAURANTE CARO" in avisos[0][1]
    assert "₡30,000.00" in avisos[0][1]


def test_mayor_a_20000_pero_menos_de_tres_veces_no_avisa(conn):
    otros = _categoria(conn, "Otros")
    for i in range(5):
        _gasto(conn, f"2026-10-0{i + 1}", 1000000, otros)  # mediana ₡10,000
    conn.execute("UPDATE transactions SET creada_en = '2000-01-01T00:00:00-06:00'")
    desde = ahora_iso()
    _gasto(conn, "2026-10-20", 2500000, otros)  # ₡25,000 = 2.5×
    assert alertas.gastos_atipicos(conn, desde) == []


def test_sin_suficiente_historia_no_avisa(conn, avisos):
    salud = _categoria(conn, "Salud")
    _gasto(conn, "2026-10-01", 100000, salud)
    conn.execute("UPDATE transactions SET creada_en = '2000-01-01T00:00:00-06:00'")
    desde = ahora_iso()
    _gasto(conn, "2026-10-20", 9000000, salud)
    assert alertas.avisar_atipicos(conn, desde) == 0


def test_sinpe_no_muestra_el_nombre(conn, historia, avisos):
    sinpe = _cuenta(conn, "sinpe")
    desde = ahora_iso()
    _gasto(conn, "2026-10-20", 4000000, historia, cuenta_id=sinpe, nombre="NOMBRE APELLIDO")
    assert alertas.avisar_atipicos(conn, desde) == 1
    assert "NOMBRE" not in avisos[0][1]
    assert "un SINPE" in avisos[0][1]
