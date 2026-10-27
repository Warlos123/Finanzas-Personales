import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from conftest import leer_evento_sms, leer_fixture  # noqa: E402
from finanzas import db, ingesta  # noqa: E402
from finanzas.web.app import crear_app  # noqa: E402

LOCAL = "http://127.0.0.1:8765"
ORIGEN = {"Origin": LOCAL}
RECIBIDO = "2026-10-26T08:45:00-06:00"


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "web.db"


@pytest.fixture
def cliente(ruta):
    conn = db.conectar(ruta)
    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/una_fila.html"), RECIBIDO)
    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/varias_filas.html"), RECIBIDO)
    evento = leer_evento_sms("almuerzo.json")
    ingesta.importar_evento(conn, "sms_4066", evento["body"], evento["received_at"])
    conn.close()
    return TestClient(crear_app(ruta), base_url=LOCAL)


def _consultar(ruta, sql, parametros=()):
    conn = db.conectar(ruta)
    try:
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def _id_categoria(ruta, nombre):
    return _consultar(ruta, "SELECT id FROM categories WHERE nombre = ?", (nombre,))[0]["id"]


def _id_transaccion(ruta, llave):
    return _consultar(ruta, "SELECT id FROM transactions WHERE llave_unica = ?", (llave,))[0]["id"]


def test_todas_las_paginas_cargan(cliente, ruta):
    paginas = ["/", "/?mes=2026-09", "/transacciones", "/transacciones?mes=&q=soda&ignoradas=1",
               "/bandeja", "/ingresos", "/reglas", "/cuentas",
               f"/transacciones/{_id_transaccion(ruta, 'bcr:00123456:100000000001')}"]
    for i in range(len(paginas)):
        respuesta = cliente.get(paginas[i])
        assert respuesta.status_code == 200, paginas[i]
    assert "SINPE TP SAN JOSE CR" in cliente.get("/bandeja").text
    assert "Bandeja (5)" in cliente.get("/").text


def test_rechaza_host_y_origen_ajenos(ruta):
    db.conectar(ruta).close()
    ajeno = TestClient(crear_app(ruta), base_url="http://ataque.example:8765")
    assert ajeno.get("/").status_code == 400

    local = TestClient(crear_app(ruta), base_url=LOCAL)
    assert local.post("/reglas/aplicar").status_code == 403
    assert local.post("/reglas/aplicar", headers={"Origin": "http://ataque.example"}).status_code == 403
    assert local.post("/reglas/aplicar", headers=ORIGEN, follow_redirects=False).status_code == 303


def test_aceptacion_categorizar_pendiente_crea_regla_y_aplica_a_la_siguiente(cliente, ruta):
    """Etapa 2: categorizo un pendiente, se crea la regla y la siguiente igual llega categorizada."""
    transaccion = _id_transaccion(ruta, "bcr:00123456:100000000001")
    transporte = _id_categoria(ruta, "Transporte")

    respuesta = cliente.post(
        "/bandeja",
        data={"id": transaccion, f"categoria_{transaccion}": transporte, f"tipo_{transaccion}": "gasto",
              f"regla_{transaccion}": "1", f"campo_{transaccion}": "comercio",
              f"patron_{transaccion}": "SINPE TP SAN JOSE CR"},
        headers=ORIGEN,
    )
    assert respuesta.status_code == 200
    assert "1 reglas nuevas" in respuesta.text
    assert len(_consultar(ruta, "SELECT * FROM rules")) == 1

    conn = db.conectar(ruta)
    siguiente = leer_fixture("bcr/una_fila.html").replace("00123456", "00555555").replace("100000000001", "100000000055")
    ingesta.importar_evento(conn, "gmail_bcr", siguiente, RECIBIDO)
    conn.close()
    nueva = _consultar(ruta, "SELECT categoria_id FROM transactions WHERE llave_unica = 'bcr:00555555:100000000055'")
    assert nueva[0]["categoria_id"] == transporte
    assert "SINPE TP SAN JOSE CR" not in cliente.get("/bandeja").text


def test_bandeja_sin_elegir_nada_avisa_y_no_cambia(cliente, ruta):
    transaccion = _id_transaccion(ruta, "bcr:00200001:100000000010")
    respuesta = cliente.post(
        "/bandeja", data={"id": transaccion, f"tipo_{transaccion}": "gasto"}, headers=ORIGEN
    )
    assert "No elegiste ninguna categoría" in respuesta.text
    fila = _consultar(ruta, "SELECT categoria_id, estado FROM transactions WHERE id = ?", (transaccion,))[0]
    assert (fila["categoria_id"], fila["estado"]) == (None, "confirmada")


def test_bandeja_guarda_varias_filas_de_una_vez(cliente, ruta):
    """Elegir categoría en varias filas y guardar una sola vez: no se pierde ninguna."""
    super_ = _id_transaccion(ruta, "bcr:00200001:100000000010")
    soda = _id_transaccion(ruta, "bcr:00200004:100000000013")
    streaming = _id_transaccion(ruta, "bcr:00200002:100000000011")
    sinpe = _id_transaccion(ruta, "sinpe:2026102215283000000000001")
    supermercado = _id_categoria(ruta, "Supermercado")
    comida = _id_categoria(ruta, "Comida")
    datos = {
        "id": [super_, soda, streaming, sinpe],
        f"categoria_{super_}": supermercado, f"tipo_{super_}": "gasto",
        f"categoria_{soda}": comida, f"tipo_{soda}": "gasto", f"regla_{soda}": "1",
        f"campo_{soda}": "comercio", f"patron_{soda}": "SODA",
        f"categoria_{streaming}": "", f"tipo_{streaming}": "gasto", f"ignorar_{streaming}": "1",
        f"categoria_{sinpe}": "", f"tipo_{sinpe}": "gasto",
    }

    respuesta = cliente.post("/bandeja", data=datos, headers=ORIGEN)

    assert "2 guardadas" in respuesta.text
    assert "1 ignoradas" in respuesta.text
    categorias = {}
    filas = _consultar(ruta, "SELECT id, categoria_id, estado FROM transactions")
    for i in range(len(filas)):
        categorias[filas[i]["id"]] = (filas[i]["categoria_id"], filas[i]["estado"])
    assert categorias[super_] == (supermercado, "confirmada")
    assert categorias[soda] == (comida, "confirmada")
    assert categorias[streaming] == (None, "ignorada")
    assert categorias[sinpe] == (None, "confirmada")  # sin elegir: no cambia
    assert len(_consultar(ruta, "SELECT * FROM rules")) == 1


def test_bandeja_lo_elegido_a_mano_gana_sobre_una_regla_nueva(cliente, ruta):
    soda = _id_transaccion(ruta, "bcr:00200004:100000000013")
    super_ = _id_transaccion(ruta, "bcr:00200001:100000000010")
    comida = _id_categoria(ruta, "Comida")
    supermercado = _id_categoria(ruta, "Supermercado")
    # La regla "E" de la soda también calzaría con "SUPERMERCADO EJEMPLO".
    datos = {
        "id": [soda, super_],
        f"categoria_{soda}": comida, f"regla_{soda}": "1", f"campo_{soda}": "comercio", f"patron_{soda}": "E",
        f"categoria_{super_}": supermercado,
    }
    cliente.post("/bandeja", data=datos, headers=ORIGEN)
    fila = _consultar(ruta, "SELECT categoria_id FROM transactions WHERE id = ?", (super_,))[0]
    assert fila["categoria_id"] == supermercado


def test_editar_transaccion(cliente, ruta):
    transaccion = _id_transaccion(ruta, "sinpe:2026102215283000000000001")
    respuesta = cliente.post(
        f"/transacciones/{transaccion}",
        data={"fecha": "2026-10-22T15:30", "monto": "3,000.00", "moneda": "CRC", "tipo": "reembolsable",
              "categoria_id": "", "cuenta_id": "", "comercio": "OTRA PERSONA", "notas": "me debe",
              "estado": "confirmada"},
        headers=ORIGEN,
    )
    assert "Guardado" in respuesta.text
    fila = _consultar(ruta, "SELECT * FROM transactions WHERE id = ?", (transaccion,))[0]
    assert (fila["monto_centimos"], fila["tipo"], fila["notas"]) == (300000, "reembolsable", "me debe")
    assert fila["fecha_hora"] == "2026-10-22T15:30:00-06:00"
    assert fila["editada_en"] is not None

    malo = cliente.post(f"/transacciones/{transaccion}", data={"fecha": "x", "monto": "1"}, headers=ORIGEN)
    assert "Fecha inválida" in malo.text


def test_volver_solo_acepta_rutas_internas(cliente, ruta):
    transaccion = _id_transaccion(ruta, "bcr:00123456:100000000001")
    pagina = cliente.get(f"/transacciones/{transaccion}?volver=javascript:alert(1)").text
    assert "javascript:alert" not in pagina


def test_ingresos_manuales_y_recurrentes(cliente, ruta):
    respuesta = cliente.post(
        "/ingresos",
        data={"fecha": "2026-10-20", "monto": "50,000", "moneda": "CRC", "comercio": "SINPE de Ana",
              "notas": "venta", "extraordinario": "1"},
        headers=ORIGEN,
    )
    assert "Ingreso agregado" in respuesta.text
    assert "SINPE de Ana" in cliente.get("/ingresos?mes=2026-10").text
    ingreso = _consultar(ruta, "SELECT * FROM transactions WHERE tipo = 'ingreso'")[0]
    assert ingreso["extraordinario"] == 1

    cliente.post(f"/transacciones/{ingreso['id']}/borrar", headers=ORIGEN)
    assert _consultar(ruta, "SELECT COUNT(*) AS n FROM transactions WHERE tipo = 'ingreso'")[0]["n"] == 0

    respuesta = cliente.post(
        "/recurrentes",
        data={"nombre": "Salario", "monto": "500000", "moneda": "CRC", "dia": "1", "cuenta_id": "",
              "activa": "1", "desde": "2026-09-01"},
        headers=ORIGEN,
    )
    assert "Recurrente guardado" in respuesta.text
    generados = _consultar(ruta, "SELECT COUNT(*) AS n FROM transactions WHERE llave_unica LIKE 'recurrente:%'")
    assert generados[0]["n"] >= 2


def test_reglas_cuentas_categorias_y_tipo_de_cambio(cliente, ruta):
    comida = _id_categoria(ruta, "Comida")
    respuesta = cliente.post(
        "/reglas", data={"campo": "comercio", "patron": "soda", "categoria_id": comida, "tipo_forzado": ""},
        headers=ORIGEN,
    )
    assert "1 transacciones categorizadas" in respuesta.text
    regla = _consultar(ruta, "SELECT id FROM rules")[0]["id"]
    cliente.post(f"/reglas/{regla}", data={"campo": "comercio", "patron": "SODA LA", "categoria_id": comida,
                                           "tipo_forzado": "", "prioridad": "5"}, headers=ORIGEN)
    assert _consultar(ruta, "SELECT patron FROM rules")[0]["patron"] == "SODA LA"
    cliente.post(f"/reglas/{regla}/borrar", headers=ORIGEN)
    assert _consultar(ruta, "SELECT COUNT(*) AS n FROM rules")[0]["n"] == 0

    cliente.post("/cuentas", data={"nombre": "Efectivo", "tipo": "efectivo", "ultimos4": "", "moneda": "CRC"},
                 headers=ORIGEN)
    assert "Efectivo" in cliente.get("/cuentas").text

    cliente.post("/categorias", data={"nombre": "Café", "padre_id": comida}, headers=ORIGEN)
    assert "Comida / Café" in cliente.get("/cuentas").text

    assert "inválido" in cliente.post("/ajustes/tipo-cambio", data={"tipo_cambio": "abc"}, headers=ORIGEN).text
    cliente.post("/ajustes/tipo-cambio", data={"tipo_cambio": "505.50"}, headers=ORIGEN)
    assert _consultar(ruta, "SELECT valor FROM settings WHERE clave = 'tipo_cambio_usd'")[0]["valor"] == "505.50"


def test_exportar_csv_con_filtros(cliente):
    respuesta = cliente.get("/transacciones.csv?mes=2026-10&q=soda")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/csv")
    assert 'filename="transacciones-2026-10.csv"' in respuesta.headers["content-disposition"]
    texto = respuesta.content.decode("utf-8-sig")
    lineas = texto.strip().splitlines()
    assert lineas[0].startswith("fecha_hora,cuenta,comercio_o_destinatario")
    assert len(lineas) == 2
    assert "SODA LA ESQUINA" in lineas[1]
    assert ",1500.00,CRC," in lineas[1]
    assert "Exportar a CSV" in cliente.get("/transacciones?mes=2026-10").text


def test_presupuesto_desde_categorias_y_en_el_dashboard(cliente, ruta):
    comida = _id_categoria(ruta, "Comida")
    cliente.post(f"/categorias/{comida}", data={"nombre": "Comida", "padre_id": "", "presupuesto": "50,000"},
                 headers=ORIGEN)
    assert _consultar(ruta, "SELECT monto_mensual_centimos FROM budgets")[0][0] == 5000000
    assert 'value="50000.00"' in cliente.get("/cuentas").text
    assert "Presupuestos" in cliente.get("/?mes=2026-10").text

    cliente.post(f"/categorias/{comida}", data={"nombre": "Comida", "padre_id": "", "presupuesto": ""},
                 headers=ORIGEN)
    assert _consultar(ruta, "SELECT COUNT(*) FROM budgets")[0][0] == 0


def test_pagina_de_graficos(cliente):
    pagina = cliente.get("/graficos?mes=2026-10")
    assert pagina.status_code == 200
    assert "<svg" in pagina.text
    assert "Gastos más grandes de octubre 2026" in pagina.text
    assert "SUPERMERCADO EJEMPLO" in pagina.text
    assert "Ver como tabla" in pagina.text


def test_clic_en_columna_muestra_los_gastos_mas_grandes_de_ese_mes(cliente):
    pagina = cliente.get("/graficos?mes=2026-10").text
    assert 'href="/graficos?mes=2026-10&amp;detalle=2026-09#grandes"' in pagina
    assert 'id="grandes"' in pagina

    septiembre = cliente.get("/graficos?mes=2026-10&detalle=2026-09").text
    assert "Gastos más grandes de septiembre 2026" in septiembre
    assert "SUPERMERCADO EJEMPLO" not in septiembre
    assert "Gráficos · octubre 2026" in septiembre

    # Fuera de los 12 meses o inválido: se queda en el mes del gráfico.
    invalidos = ["2025-01", "x"]
    for i in range(len(invalidos)):
        pagina = cliente.get(f"/graficos?mes=2026-10&detalle={invalidos[i]}").text
        assert "Gastos más grandes de octubre 2026" in pagina


def test_css_con_version_para_no_usar_cache_vieja(cliente):
    pagina = cliente.get("/").text
    assert "/static/estilo.css?v=" in pagina
    svg = cliente.get("/graficos?mes=2026-10").text
    assert 'class="zona"' in svg and 'fill="transparent"' in svg
