import subprocess

import pytest

from conftest import leer_evento_sms, leer_fixture
from finanzas import estado_cuenta, ingesta, reconciliacion

RECIBIDO = "2026-10-26T08:45:00-06:00"


def _estado():
    return estado_cuenta.leer(leer_fixture("estado_cuenta/ahorros_octubre.txt"))


def _importar_fixtures(conn):
    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/una_fila.html"), RECIBIDO)
    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/varias_filas.html"), RECIBIDO)
    nombres = ["almuerzo.json", "pasaje.json"]
    for i in range(len(nombres)):
        evento = leer_evento_sms(nombres[i])
        ingesta.importar_evento(conn, "sms_4066", evento["body"], evento["received_at"])


def test_lee_el_estado_y_distingue_debitos_de_creditos():
    estado = _estado()
    assert (estado.moneda, estado.desde, estado.hasta) == ("CRC", "2026-10-01", "2026-10-31")
    assert len(estado.movimientos) == 12
    assert estado.saldo_anterior == 50000000 and estado.saldo_final == 58021194

    mesada = estado.movimientos[0]
    assert (mesada.tipo, mesada.detalle, mesada.credito, mesada.clase) == (
        "TRANSFERENC BANCOBCR", "SALARIO OCTUBRE", True, "otro")
    comision = estado.movimientos[3]
    assert (comision.tarjeta, comision.documento, comision.credito) == (None, "4321", False)
    parqueo = estado.movimientos[4]
    assert (parqueo.tarjeta, parqueo.documento, parqueo.clase, parqueo.texto) == (
        "4321", "77777", "compra", "PARQUEO CENTRAL")
    assert estado.movimientos[2].clase == "interno"
    # La segunda página tiene las columnas corridas: igual se distingue el crédito.
    assert estado.movimientos[11].credito and estado.movimientos[11].monto_centimos == 51234


def test_sinpe_sin_telefono_ni_relleno():
    estado = _estado()
    assert estado.movimientos[5].texto == "Almuerzo"
    assert estado.movimientos[6].texto == "ana"


def test_rechaza_si_no_cuadra_con_los_totales():
    texto = leer_fixture("estado_cuenta/ahorros_octubre.txt")
    with pytest.raises(ValueError, match="totales"):
        estado_cuenta.leer(texto.replace("2,500.00", "2,600.00", 1))
    with pytest.raises(ValueError, match="período"):
        estado_cuenta.leer("Saldo Anterior : 1.00 COLONES")


def test_texto_de_pdf_con_pdftotext(monkeypatch):
    llamadas = []

    def falso_run(comando, **kwargs):
        llamadas.append(comando)
        return subprocess.CompletedProcess(comando, 0, stdout="texto".encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", falso_run)
    assert estado_cuenta.texto_de_pdf(b"%PDF-1.7 ...") == "texto"
    assert llamadas[0][:4] == ["pdftotext", "-layout", "-enc", "UTF-8"]
    with pytest.raises(ValueError, match="no es un PDF"):
        estado_cuenta.texto_de_pdf(b"hola")

    def sin_pdftotext(comando, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", sin_pdftotext)
    with pytest.raises(ValueError, match="poppler"):
        estado_cuenta.texto_de_pdf(b"%PDF-1.7 ...")


def test_reconciliar_contra_correos_y_sms(conn):
    _importar_fixtures(conn)
    resultado = reconciliacion.reconciliar(conn, _estado())

    coinciden = set()
    for i in range(len(resultado.coinciden)):
        coinciden.add(resultado.coinciden[i].indice)
    # Por autorización: supermercado, streaming (USD en la app) y SINPE TP; por monto y fecha: el SINPE.
    assert coinciden == {5, 7, 8, 10}
    assert len(resultado.montos_distintos) == 1
    assert resultado.montos_distintos[0].indice == 9
    assert resultado.montos_distintos[0].transaccion["monto_centimos"] == 150000

    faltan = []
    for i in range(len(resultado.faltan)):
        faltan.append((resultado.faltan[i].indice, resultado.faltan[i].tipo_sugerido))
    assert faltan == [(0, "ingreso"), (1, "ingreso"), (3, "gasto"), (4, "gasto"), (6, "ingreso"), (11, "ingreso")]
    assert len(resultado.internos) == 1

    # El pasaje por SINPE (23/10) está en la app pero no en el estado.
    assert len(resultado.solo_en_app) == 1
    assert resultado.solo_en_app[0]["llave_unica"] == "sinpe:2026102307150000000000002"


def test_agregar_e_ignorar_no_se_duplica_al_subir_de_nuevo(conn):
    _importar_fixtures(conn)
    estado = _estado()
    with conn:
        texto = leer_fixture("estado_cuenta/ahorros_octubre.txt")
        estado_id = reconciliacion.guardar(conn, texto)
        assert reconciliacion.guardar(conn, texto) == estado_id
        agregadas, ignoradas = reconciliacion.agregar(conn, estado, [(0, "ingreso"), (4, "gasto"), (6, "ignorar"), (2, "gasto")])
    assert (agregadas, ignoradas) == (2, 1)  # el interno (2) se salta

    mesada = conn.execute(
        "SELECT t.*, a.nombre AS cuenta FROM transactions t JOIN accounts a ON a.id = t.cuenta_id "
        "WHERE llave_unica = 'estado:2026-10-01:1000001:30000000'"
    ).fetchone()
    assert (mesada["tipo"], mesada["comercio_o_destinatario"], mesada["cuenta"]) == (
        "ingreso", "SALARIO OCTUBRE", "Cuenta de ahorros BCR")
    parqueo = conn.execute(
        "SELECT t.*, a.ultimos4 FROM transactions t JOIN accounts a ON a.id = t.cuenta_id "
        "WHERE llave_unica = 'estado:2026-10-20:77777:80000'"
    ).fetchone()
    assert (parqueo["comercio_o_destinatario"], parqueo["ultimos4"], parqueo["fecha_hora"]) == (
        "PARQUEO CENTRAL", "4321", "2026-10-20T00:00:00-06:00")
    sinpe = conn.execute(
        "SELECT * FROM transactions WHERE llave_unica = 'estado:2026-10-23:50000001:300000'"
    ).fetchone()
    assert (sinpe["estado"], sinpe["tipo"], sinpe["descripcion"]) == ("ignorada", "ingreso", "ana")

    resultado = reconciliacion.reconciliar(conn, reconciliacion.obtener(conn, estado_id))
    faltan = []
    for i in range(len(resultado.faltan)):
        faltan.append(resultado.faltan[i].indice)
    assert faltan == [1, 3, 11]
    with conn:
        assert reconciliacion.agregar(conn, estado, [(0, "ingreso")]) == (0, 0)


def test_agregar_valida_indice_y_tipo(conn):
    estado = _estado()
    with pytest.raises(ValueError):
        reconciliacion.agregar(conn, estado, [(99, "gasto")])
    with pytest.raises(ValueError):
        reconciliacion.agregar(conn, estado, [(0, "regalo")])
