from datetime import date

import pytest

from finanzas import ahorros, db, metricas

HOY = date(2026, 10, 28)


def _datos(**cambios):
    datos = ahorros.DatosAhorro(
        tipo="cdp", nombre="CDP de prueba", moneda="CRC", invertido_centimos=100000000,
        valor_actual_centimos=None, tasa_anual="5.25", inicio="2026-05-01", vence="2026-11-10", notas=None,
    )
    claves = list(cambios)
    for i in range(len(claves)):
        setattr(datos, claves[i], cambios[claves[i]])
    return datos


def test_guardar_listar_y_vencimiento(conn):
    with conn:
        cdp = ahorros.guardar(conn, None, _datos())
        ahorros.guardar(conn, None, _datos(tipo="sp500", nombre="Fondo S&P 500", moneda="USD",
                                           invertido_centimos=200000, valor_actual_centimos=230000,
                                           tasa_anual=None, vence=None))
    lista = ahorros.listar(conn, HOY)
    assert len(lista) == 2
    assert lista[0].fila["id"] == cdp
    assert lista[0].fila["valor_actual_centimos"] == 100000000  # vacío = lo invertido
    assert lista[0].dias_para_vencer == 13
    assert lista[1].dias_para_vencer is None
    assert lista[1].ganancia == 30000 and lista[1].rendimiento == pytest.approx(0.15)


def test_resumen_en_colones_y_dolares_aparte_sin_tipo_de_cambio(conn):
    with conn:
        ahorros.guardar(conn, None, _datos())
        ahorros.guardar(conn, None, _datos(tipo="sp500", nombre="VOO", moneda="USD", invertido_centimos=200000,
                                           valor_actual_centimos=230000, tasa_anual=None, vence=None))
    resumen = ahorros.resumir(conn, ahorros.listar(conn, HOY))
    assert (resumen.total, resumen.sin_convertir) == (100000000, 230000)

    with conn:
        db.guardar_ajuste(conn, metricas.AJUSTE_TIPO_CAMBIO, "500")
    resumen = ahorros.resumir(conn, ahorros.listar(conn, HOY))
    assert resumen.sin_convertir == 0
    assert resumen.por_tipo == {"cdp": 100000000, "sp500": 115000000}
    assert resumen.ganancia == 15000000  # $300 de ganancia a ₡500


def test_validaciones(conn):
    malos = [{"tipo": "cripto"}, {"nombre": "  "}, {"moneda": "EUR"}, {"tasa_anual": "abc"},
             {"tasa_anual": "150"}, {"vence": "31/12/2026"}, {"invertido_centimos": -1}]
    for i in range(len(malos)):
        with pytest.raises(ValueError):
            ahorros.guardar(conn, None, _datos(**malos[i]))
    ahorro_id = ahorros.guardar(conn, None, _datos(tasa_anual="4.5%"))
    assert ahorros.obtener(conn, ahorro_id)["tasa_anual"] == "4.5"
