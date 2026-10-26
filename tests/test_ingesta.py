from conftest import leer_evento_sms, leer_fixture
from finanzas import ingesta

RECIBIDO = "2026-10-26T08:45:00-06:00"


def _contar(conn, tabla):
    return conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


def _importar_bcr(conn, nombre):
    return ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/" + nombre), RECIBIDO)


def _importar_sms(conn, nombre):
    evento = leer_evento_sms(nombre)
    return ingesta.importar_evento(conn, evento["source"], evento["body"], evento["received_at"])


def test_importar_el_mismo_correo_dos_veces_no_duplica(conn):
    _, nuevo, resumen = _importar_bcr(conn, "varias_filas.html")
    assert nuevo is True
    assert resumen.nuevas == 3

    _, nuevo, resumen = _importar_bcr(conn, "varias_filas.html")
    assert nuevo is False
    assert resumen.nuevas == 0

    assert _contar(conn, "raw_events") == 1
    assert _contar(conn, "transactions") == 3


def test_reprocesar_dos_veces_no_duplica(conn):
    _importar_bcr(conn, "una_fila.html")
    _importar_bcr(conn, "varias_filas.html")
    _importar_sms(conn, "almuerzo.json")
    _importar_sms(conn, "pasaje.json")
    assert _contar(conn, "transactions") == 6

    for i in range(2):
        resumen = ingesta.reprocesar(conn)
        assert resumen.nuevas == 0
        assert resumen.existentes == 6
        assert _contar(conn, "transactions") == 6
        assert _contar(conn, "raw_events") == 4
        assert _contar(conn, "accounts") == 2


def test_reproceso_no_pisa_transacciones_editadas(conn):
    _importar_sms(conn, "almuerzo.json")
    conn.execute(
        "UPDATE transactions SET monto_centimos = 1, notas = 'corregido', editada_en = ?",
        (RECIBIDO,),
    )
    conn.commit()

    ingesta.reprocesar(conn)

    fila = conn.execute("SELECT monto_centimos, notas FROM transactions").fetchone()
    assert fila["monto_centimos"] == 1
    assert fila["notas"] == "corregido"


def test_filas_no_aprobadas_quedan_marcadas_en_raw_events(conn):
    raw_id, _, _ = _importar_bcr(conn, "varias_filas.html")
    evento = conn.execute(
        "SELECT estado_parseo, detalle_parseo FROM raw_events WHERE id = ?", (raw_id,)
    ).fetchone()
    assert evento["estado_parseo"] == "con_avisos"
    assert "Rechazada" in evento["detalle_parseo"]


def test_moneda_desconocida_crea_transaccion_pendiente(conn):
    _importar_bcr(conn, "moneda_desconocida.html")
    fila = conn.execute("SELECT moneda, estado FROM transactions").fetchone()
    assert fila["moneda"] is None
    assert fila["estado"] == "pendiente"


def test_evento_no_parseable_queda_en_error_sin_transacciones(conn):
    raw_id, _, resumen = ingesta.importar_evento(conn, "sms_4066", "texto cualquiera", RECIBIDO)
    assert resumen.error is True
    estado = conn.execute(
        "SELECT estado_parseo FROM raw_events WHERE id = ?", (raw_id,)
    ).fetchone()[0]
    assert estado == "error"
    assert _contar(conn, "transactions") == 0


def test_cuentas_se_crean_una_vez_por_tarjeta_y_para_sinpe(conn):
    _importar_bcr(conn, "una_fila.html")
    _importar_bcr(conn, "varias_filas.html")
    _importar_bcr(conn, "moneda_desconocida.html")
    _importar_sms(conn, "almuerzo.json")
    _importar_sms(conn, "pasaje.json")

    filas = conn.execute("SELECT nombre, tipo, ultimos4 FROM accounts ORDER BY id").fetchall()
    cuentas = []
    for i in range(len(filas)):
        cuentas.append((filas[i]["nombre"], filas[i]["tipo"], filas[i]["ultimos4"]))
    assert cuentas == [
        ("Tarjeta BCR ****4321", "tarjeta", "4321"),
        ("Tarjeta BCR ****8765", "tarjeta", "8765"),
        ("SINPE Móvil", "sinpe", None),
    ]
