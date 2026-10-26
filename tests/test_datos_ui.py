"""Módulos de datos usados por la UI: formato, movimientos, recurrentes y métricas."""

from datetime import date

import pytest

from conftest import leer_evento_sms, leer_fixture
from finanzas import db, formato, ingesta, metricas, movimientos, recurrentes


def _cuenta(conn, tipo="tarjeta"):
    cursor = conn.execute("INSERT INTO accounts (nombre, tipo) VALUES ('Prueba', ?)", (tipo,))
    return cursor.lastrowid


def _categoria(conn, nombre):
    return conn.execute("SELECT id FROM categories WHERE nombre = ?", (nombre,)).fetchone()["id"]


def _manual(conn, fecha, monto, tipo="gasto", moneda="CRC", cuenta_id=None, nombre=None,
            categoria_id=None, extraordinario=False):
    datos = movimientos.DatosTransaccion(
        fecha_hora=formato.fecha_desde_formulario(fecha), monto_centimos=monto, moneda=moneda,
        tipo=tipo, cuenta_id=cuenta_id, categoria_id=categoria_id, comercio_o_destinatario=nombre,
        notas=None, extraordinario=extraordinario,
    )
    return movimientos.crear_manual(conn, datos)


# --- formato ---

def test_formato_de_montos_y_fechas():
    assert formato.formatear_monto(250000, "CRC") == "₡2,500.00"
    assert formato.formatear_monto(1049, "USD") == "$10.49"
    assert formato.formatear_monto(-5, "CRC") == "-₡0.05"
    assert formato.formatear_monto(100, None) == "1.00 (?)"
    assert formato.monto_desde_texto("₡ 12,345.5") == 1234550
    assert formato.centimos_a_texto(1234550) == "12345.50"
    with pytest.raises(ValueError):
        formato.monto_desde_texto("12.345,50")
    assert formato.fecha_desde_formulario("2026-10-26T08:43") == "2026-10-26T08:43:00-06:00"
    assert formato.fecha_desde_formulario("2026-10-26") == "2026-10-26T00:00:00-06:00"
    assert formato.fecha_a_formulario("2026-10-26T14:43:00+00:00") == "2026-10-26T08:43"
    assert formato.mes_desplazado("2026-01", -1) == "2025-12"
    assert formato.mes_desplazado("2026-12", 1) == "2027-01"
    assert formato.mes_valido("2026-10")
    assert not formato.mes_valido("2026-13")


# --- movimientos ---

def test_bandeja_agrupa_por_comercio_y_excluye_negadas(conn):
    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/varias_filas.html"), "2026-10-26T08:45:00-06:00")
    html = leer_fixture("bcr/una_fila.html")
    ingesta.importar_evento(conn, "gmail_bcr", html, "2026-10-26T08:45:00-06:00")
    otra = html.replace("00123456", "00777777").replace("100000000001", "100000000077")
    ingesta.importar_evento(conn, "gmail_bcr", otra, "2026-10-26T09:45:00-06:00")

    filas = movimientos.bandeja(conn)
    nombres = []
    for i in range(len(filas)):
        nombres.append((filas[i]["comercio_o_destinatario"], filas[i]["iguales"]))
    assert nombres[0] == ("SINPE TP SAN JOSE CR", 2)
    assert len(filas) == 4  # 3 comercios aprobados del correo múltiple + SINPE TP; la negada no
    assert movimientos.contar_bandeja(conn) == 5


def test_listar_con_filtros(conn):
    cuenta = _cuenta(conn)
    comida = _categoria(conn, "Comida")
    _manual(conn, "2026-10-05", 1000, cuenta_id=cuenta, nombre="SODA", categoria_id=comida)
    _manual(conn, "2026-10-06", 2000, nombre="CINE")
    _manual(conn, "2026-09-30", 3000, nombre="SODA")
    ignorada = _manual(conn, "2026-10-07", 4000, nombre="SODA")
    movimientos.ignorar(conn, ignorada)

    assert len(movimientos.listar(conn, movimientos.Filtros(mes="2026-10"))) == 2
    assert len(movimientos.listar(conn, movimientos.Filtros(mes="2026-10", incluir_ignoradas=True))) == 3
    assert len(movimientos.listar(conn, movimientos.Filtros(texto="soda"))) == 2
    assert len(movimientos.listar(conn, movimientos.Filtros(categoria="sin"))) == 2
    assert len(movimientos.listar(conn, movimientos.Filtros(categoria=str(comida)))) == 1
    assert len(movimientos.listar(conn, movimientos.Filtros(cuenta_id=cuenta))) == 1


def test_editar_marca_editada_y_reproceso_respeta(conn):
    evento = leer_evento_sms("almuerzo.json")
    ingesta.importar_evento(conn, "sms_4066", evento["body"], evento["received_at"])
    fila = conn.execute("SELECT * FROM transactions").fetchone()
    datos = movimientos.DatosTransaccion(
        fecha_hora=fila["fecha_hora"], monto_centimos=300000, moneda="CRC", tipo="reembolsable",
        cuenta_id=fila["cuenta_id"], categoria_id=None, comercio_o_destinatario="OTRO NOMBRE",
        notas="me lo deben",
    )
    with conn:
        movimientos.actualizar(conn, fila["id"], datos)
    ingesta.reprocesar(conn)

    editada = movimientos.obtener(conn, fila["id"])
    assert editada["monto_centimos"] == 300000
    assert editada["tipo"] == "reembolsable"
    assert editada["editada_en"] is not None


def test_borrar_solo_manuales(conn):
    manual = _manual(conn, "2026-10-05", 1000, tipo="ingreso", nombre="Venta")
    assert movimientos.borrar(conn, manual) == "borrada"
    assert movimientos.obtener(conn, manual) is None

    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/una_fila.html"), "2026-10-26T08:45:00-06:00")
    importada = conn.execute("SELECT id FROM transactions").fetchone()["id"]
    with pytest.raises(ValueError):
        movimientos.borrar(conn, importada)


# --- recurrentes ---

def test_recurrentes_generan_una_vez_por_mes_y_respetan_fin_de_mes(conn):
    salario = recurrentes.guardar(conn, None, "Salario", 50000000, "CRC", 31, None, True, "2026-01-15")
    creados = recurrentes.generar(conn, date(2026, 3, 30))
    # enero 31, febrero 28; marzo 31 aún no llega
    assert creados == 2
    assert recurrentes.generar(conn, date(2026, 3, 31)) == 1
    assert recurrentes.generar(conn, date(2026, 3, 31)) == 0
    fechas = conn.execute("SELECT fecha_hora FROM transactions ORDER BY fecha_hora").fetchall()
    assert fechas[1]["fecha_hora"] == "2026-02-28T00:00:00-06:00"

    generado = conn.execute("SELECT id FROM transactions WHERE llave_unica = ?", (f"recurrente:{salario}:2026-02",)).fetchone()["id"]
    assert movimientos.borrar(conn, generado) == "ignorada"
    assert recurrentes.generar(conn, date(2026, 3, 31)) == 0


def test_recurrente_inactivo_no_genera(conn):
    recurrentes.guardar(conn, None, "Alquiler", 100, "CRC", 1, None, False, "2026-01-01")
    assert recurrentes.generar(conn, date(2026, 3, 1)) == 0


def test_recurrente_validaciones(conn):
    with pytest.raises(ValueError):
        recurrentes.guardar(conn, None, " ", 100, "CRC", 1, None, True, None)
    with pytest.raises(ValueError):
        recurrentes.guardar(conn, None, "X", 100, "CRC", 32, None, True, None)


# --- métricas ---

def test_metricas_del_mes(conn):
    tarjeta = _cuenta(conn, "tarjeta")
    sinpe = _cuenta(conn, "sinpe")
    comida = _categoria(conn, "Comida")
    _manual(conn, "2026-10-01", 100000000, tipo="ingreso", nombre="Salario")
    _manual(conn, "2026-10-02", 20000000, tipo="ingreso", nombre="Bono", extraordinario=True)
    _manual(conn, "2026-10-03", 3000000, cuenta_id=tarjeta, nombre="SODA", categoria_id=comida)
    _manual(conn, "2026-10-04", 1000000, cuenta_id=tarjeta, nombre="SODA", categoria_id=comida)
    _manual(conn, "2026-10-05", 2000000, cuenta_id=sinpe, nombre="PERSONA")
    _manual(conn, "2026-10-06", 1000, moneda="USD", cuenta_id=tarjeta, nombre="STREAMING")
    _manual(conn, "2026-10-07", 9999999, tipo="transferencia", nombre="PAGO TARJETA")
    _manual(conn, "2026-10-08", 500000, tipo="reembolsable", cuenta_id=sinpe, nombre="AMIGO")
    _manual(conn, "2026-09-15", 4000000, cuenta_id=tarjeta, nombre="SODA")

    resumen = metricas.resumen_mes(conn, "2026-10", date(2026, 10, 10))

    assert resumen.gasto == 6000000
    assert resumen.ingresos == 120000000
    assert resumen.ingresos_extraordinarios == 20000000
    assert resumen.balance == 114000000
    assert resumen.transferencias == 9999999
    assert resumen.reembolsables == 500000
    assert resumen.usd_gasto_sin_convertir == 1000
    assert resumen.promedio_diario == 600000
    assert resumen.proyeccion == 600000 * 31
    assert resumen.por_categoria[0] == ("Comida", 4000000, 4000000 / 6000000)
    assert resumen.top_comercios[0] == ("SODA", 4000000, 2)
    assert resumen.top_destinatarios[0] == ("PERSONA", 2000000, 1)
    assert resumen.gasto_anterior == 4000000
    assert resumen.tasa_ahorro == pytest.approx(114000000 / 120000000)


def test_metricas_convierten_usd_con_tipo_de_cambio(conn):
    _manual(conn, "2026-09-06", 1000, moneda="USD", nombre="STREAMING")
    with conn:
        db.guardar_ajuste(conn, metricas.AJUSTE_TIPO_CAMBIO, "505.50")
    resumen = metricas.resumen_mes(conn, "2026-09", date(2026, 10, 10))
    assert resumen.gasto == 505500
    assert resumen.usd_gasto_sin_convertir == 0
    assert resumen.proyeccion == resumen.gasto
    assert resumen.dias_transcurridos == 30
