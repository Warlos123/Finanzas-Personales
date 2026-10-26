import pytest

from conftest import leer_evento_sms, leer_fixture
from finanzas import ingesta, reglas

RECIBIDO = "2026-10-26T08:45:00-06:00"


def _categoria(conn, nombre):
    return conn.execute("SELECT id FROM categories WHERE nombre = ?", (nombre,)).fetchone()["id"]


def _importar_bcr(conn, html):
    return ingesta.importar_evento(conn, "gmail_bcr", html, RECIBIDO)


def _categoria_de(conn, llave):
    return conn.execute(
        "SELECT categoria_id, tipo FROM transactions WHERE llave_unica = ?", (llave,)
    ).fetchone()


def test_categorias_base_precargadas(conn):
    total = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    assert total == 8
    assert _categoria(conn, "Transporte") is not None


def test_regla_categoriza_la_siguiente_transaccion_igual(conn):
    """Criterio de aceptación de la Etapa 2."""
    html = leer_fixture("bcr/una_fila.html")
    _importar_bcr(conn, html)
    assert _categoria_de(conn, "bcr:00123456:100000000001")["categoria_id"] is None

    transporte = _categoria(conn, "Transporte")
    with conn:
        reglas.crear_regla(conn, "comercio", "SINPE TP SAN JOSE CR", transporte)

    siguiente = html.replace("00123456", "00999999").replace("100000000001", "100000000099")
    _importar_bcr(conn, siguiente)
    assert _categoria_de(conn, "bcr:00999999:100000000099")["categoria_id"] == transporte


def test_aplicar_a_existentes_sin_categoria(conn):
    _importar_bcr(conn, leer_fixture("bcr/varias_filas.html"))
    comida = _categoria(conn, "Comida")
    with conn:
        reglas.crear_regla(conn, "comercio", "soda", comida)
        cambiadas = reglas.aplicar_reglas(conn)
    assert cambiadas == 1
    assert _categoria_de(conn, "bcr:00200004:100000000013")["categoria_id"] == comida
    assert _categoria_de(conn, "bcr:00200001:100000000010")["categoria_id"] is None


def test_comercio_no_aplica_a_sinpe_y_destinatario_si(conn):
    evento = leer_evento_sms("almuerzo.json")
    ingesta.importar_evento(conn, "sms_4066", evento["body"], evento["received_at"])
    llave = "sinpe:2026102215283000000000001"
    otros = _categoria(conn, "Otros")
    comida = _categoria(conn, "Comida")

    with conn:
        reglas.crear_regla(conn, "comercio", "NOMBRE APELLIDO", otros)
        reglas.aplicar_reglas(conn)
    assert _categoria_de(conn, llave)["categoria_id"] is None

    with conn:
        reglas.crear_regla(conn, "descripcion", "almuerzo", comida)
        reglas.aplicar_reglas(conn)
    assert _categoria_de(conn, llave)["categoria_id"] == comida


def test_prioridad_y_tipo_forzado(conn):
    _importar_bcr(conn, leer_fixture("bcr/una_fila.html"))
    with conn:
        reglas.crear_regla(conn, "comercio", "SINPE", _categoria(conn, "Otros"), prioridad=20)
        reglas.crear_regla(conn, "comercio", "sinpe tp", None, tipo_forzado="transferencia", prioridad=10)
        reglas.aplicar_reglas(conn)
    fila = _categoria_de(conn, "bcr:00123456:100000000001")
    assert fila["tipo"] == "transferencia"
    assert fila["categoria_id"] is None


def test_no_toca_transacciones_categorizadas_ni_editadas(conn):
    _importar_bcr(conn, leer_fixture("bcr/varias_filas.html"))
    salud = _categoria(conn, "Salud")
    with conn:
        conn.execute("UPDATE transactions SET categoria_id = ? WHERE llave_unica = 'bcr:00200004:100000000013'", (salud,))
        conn.execute("UPDATE transactions SET editada_en = 'x' WHERE llave_unica = 'bcr:00200001:100000000010'")
        reglas.crear_regla(conn, "comercio", "E", _categoria(conn, "Otros"))
        reglas.aplicar_reglas(conn)
    assert _categoria_de(conn, "bcr:00200004:100000000013")["categoria_id"] == salud
    assert _categoria_de(conn, "bcr:00200001:100000000010")["categoria_id"] is None


def test_regla_invalida(conn):
    with pytest.raises(ValueError):
        reglas.crear_regla(conn, "comercio", "   ", 1)
    with pytest.raises(ValueError):
        reglas.crear_regla(conn, "comercio", "X", None)
    with pytest.raises(ValueError):
        reglas.crear_regla(conn, "otro", "X", 1)
