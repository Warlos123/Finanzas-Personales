from datetime import date

from finanzas import formato, movimientos, suscripciones


def _cuenta(conn, tipo):
    return conn.execute("INSERT INTO accounts (nombre, tipo) VALUES ('C', ?)", (tipo,)).lastrowid


def _cobro(conn, fecha, monto, comercio, cuenta_id, moneda="CRC"):
    datos = movimientos.DatosTransaccion(
        fecha_hora=formato.fecha_desde_formulario(fecha), monto_centimos=monto, moneda=moneda,
        tipo="gasto", cuenta_id=cuenta_id, categoria_id=None, comercio_o_destinatario=comercio, notas=None,
    )
    movimientos.crear_manual(conn, datos)


def test_detecta_cobro_mensual_de_monto_parecido(conn):
    tarjeta = _cuenta(conn, "tarjeta")
    fechas = ["2026-07-10", "2026-08-10", "2026-09-11", "2026-10-10"]
    for i in range(len(fechas)):
        _cobro(conn, fechas[i], 999 + i, "SERVICIO STREAMING", tarjeta, moneda="USD")
    # Ruido: compras frecuentes, montos muy distintos, y algo que dejó de cobrarse.
    for i in range(1, 9):
        _cobro(conn, f"2026-10-0{i}", 71000, "SINPE TP SAN JOSE CR", tarjeta)
    _cobro(conn, "2026-08-05", 500000, "TIENDA", tarjeta)
    _cobro(conn, "2026-09-05", 2500000, "TIENDA", tarjeta)
    _cobro(conn, "2026-10-05", 900000, "TIENDA", tarjeta)
    for mes in ("04", "05", "06"):
        _cobro(conn, f"2026-{mes}-15", 300000, "GIMNASIO VIEJO", tarjeta)

    encontradas = suscripciones.detectar(conn, date(2026, 10, 27))

    assert len(encontradas) == 1
    s = encontradas[0]
    assert (s.comercio, s.moneda, s.cobros) == ("SERVICIO STREAMING", "USD", 4)
    assert s.monto_tipico == 1000
    assert s.ultimo_cobro == date(2026, 10, 10)
    assert s.proximo_cobro == date(2026, 11, 10)  # mediana de intervalos 31, 32 y 29 = 31


def test_los_sinpe_mensuales_no_son_suscripciones(conn):
    sinpe = _cuenta(conn, "sinpe")
    for mes in ("08", "09", "10"):
        _cobro(conn, f"2026-{mes}-01", 5000000, "PERSONA ALQUILER", sinpe)
    assert suscripciones.detectar(conn, date(2026, 10, 27)) == []
