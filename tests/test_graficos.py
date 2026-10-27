from finanzas import formato, graficos, movimientos


def _gasto(conn, fecha, monto, moneda="CRC", tipo="gasto"):
    datos = movimientos.DatosTransaccion(
        fecha_hora=formato.fecha_desde_formulario(fecha), monto_centimos=monto, moneda=moneda, tipo=tipo,
        cuenta_id=None, categoria_id=None, comercio_o_destinatario="X", notas=None,
    )
    movimientos.crear_manual(conn, datos)


def test_gasto_por_mes_doce_meses_con_ceros(conn):
    _gasto(conn, "2026-10-05", 3000000)
    _gasto(conn, "2026-10-06", 2000000)
    _gasto(conn, "2026-01-15", 1000000)
    _gasto(conn, "2026-10-07", 9000000, tipo="transferencia")
    _gasto(conn, "2025-10-31", 7000000)  # fuera de la ventana

    datos = graficos.gasto_por_mes(conn, "2026-10")

    assert len(datos) == 12
    assert datos[0] == ("2025-11", 0)
    assert datos[-1] == ("2026-10", 5000000)
    assert ("2026-01", 1000000) in datos


def test_ejes_redondos_y_compactos():
    assert graficos.paso_redondo(37_000_000) == 10_000_000
    assert graficos.paso_redondo(0) == 100_000
    assert graficos.compacto(25_000_000) == "₡250K"
    assert graficos.compacto(120_000_000) == "₡1.2M"
    assert graficos.compacto(100_000_000) == "₡1M"
    assert graficos.compacto(50_000) == "₡500"


def test_geometria_de_columnas():
    datos = [("2026-09", 1000000), ("2026-10", 4000000), ("2026-11", 0)]
    g = graficos.grafico_meses(datos, "2026-10")
    resaltadas = []
    for i in range(len(g.columnas)):
        resaltadas.append(g.columnas[i].resaltada)
    assert resaltadas == [False, True, False]
    assert g.columnas[2].trazo == ""  # un mes sin gasto no dibuja columna
    for i in range(len(g.columnas)):
        assert g.columnas[i].ancho <= graficos.GROSOR_MAXIMO
    assert g.marcas[0].texto == "₡0"
    assert g.columnas[0].anio == "2026"
