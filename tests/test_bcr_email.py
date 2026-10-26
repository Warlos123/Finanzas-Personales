import pytest

from conftest import leer_fixture
from finanzas.parsers import bcr_email
from finanzas.parsers.base import ErrorParseo

RECIBIDO = "2026-10-26T08:45:00-06:00"


def test_una_fila_aprobada():
    resultado = bcr_email.parsear(leer_fixture("bcr/una_fila.html"), RECIBIDO)

    assert resultado.avisos == []
    assert len(resultado.transacciones) == 1
    tx = resultado.transacciones[0]
    assert tx.llave_unica == "bcr:00123456:100000000001"
    assert tx.fecha_hora == "2026-10-26T08:43:33-06:00"
    assert tx.monto_centimos == 71000
    assert tx.moneda == "CRC"
    assert tx.tipo == "gasto"
    assert tx.comercio_o_destinatario == "SINPE TP SAN JOSE CR"
    assert tx.estado == "confirmada"
    assert tx.cuenta_tipo == "tarjeta"
    assert tx.cuenta_ultimos4 == "4321"


def test_varias_filas_parsea_todas_y_omite_no_aprobadas():
    resultado = bcr_email.parsear(leer_fixture("bcr/varias_filas.html"), RECIBIDO)

    assert len(resultado.transacciones) == 3
    llaves = []
    for i in range(len(resultado.transacciones)):
        llaves.append(resultado.transacciones[i].llave_unica)
    assert llaves == [
        "bcr:00200001:100000000010",
        "bcr:00200002:100000000011",
        "bcr:00200004:100000000013",
    ]
    assert resultado.transacciones[0].monto_centimos == 1234550
    assert resultado.transacciones[1].moneda == "USD"
    assert resultado.transacciones[1].monto_centimos == 999
    assert len(resultado.avisos) == 1
    assert "Rechazada" in resultado.avisos[0]


def test_moneda_desconocida_queda_pendiente_con_aviso():
    resultado = bcr_email.parsear(leer_fixture("bcr/moneda_desconocida.html"), RECIBIDO)

    tx = resultado.transacciones[0]
    assert tx.moneda is None
    assert tx.estado == "pendiente"
    assert tx.cuenta_ultimos4 == "8765"
    assert len(resultado.avisos) == 1
    assert "EURO" in resultado.avisos[0]


def test_sin_tabla_de_transacciones_es_error():
    html = "<html><body>Transacciones en su tarjeta BCR: ****-****-****-4321</body></html>"
    with pytest.raises(ErrorParseo):
        bcr_email.parsear(html, RECIBIDO)


def test_sin_numero_de_tarjeta_es_error():
    html = leer_fixture("bcr/una_fila.html").replace("****-****-****-4321", "")
    with pytest.raises(ErrorParseo):
        bcr_email.parsear(html, RECIBIDO)


def test_fecha_invalida_es_error():
    html = leer_fixture("bcr/una_fila.html").replace("26/10/2026 08:43:33", "2026-10-26")
    with pytest.raises(ErrorParseo):
        bcr_email.parsear(html, RECIBIDO)


def test_celdas_sin_cerrar():
    html = (
        "<p>Transacciones en su tarjeta BCR: ****-****-****-1111</p><table>"
        "<tr><td>Fecha<td>Autorización<td>No. Referencia<td>Monto<td>Moneda<td>Comercio<td>Estado"
        "<tr><td>01/10/2026 09:00:00<td>00400001<td>100000000030<td>100.00"
        "<td>COLON COSTA RICA<td>PANADERIA<td>APROBADA"
        "</table>"
    )
    resultado = bcr_email.parsear(html, RECIBIDO)
    assert len(resultado.transacciones) == 1
    assert resultado.transacciones[0].llave_unica == "bcr:00400001:100000000030"
