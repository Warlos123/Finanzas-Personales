import pytest

from conftest import leer_evento_sms
from finanzas.parsers import sinpe_sms
from finanzas.parsers.base import ErrorParseo

RECIBIDO = "2026-10-22T15:28:41-06:00"


def _cuerpo(monto="2,500.00", moneda="Colones", resto="Almuerzo*********"):
    return (
        f"Ha enviado {monto} {moneda} a NOMBRE APELLIDO APELLIDO por SINPE Movil, {resto}. "
        "Comprobante 2026102215283000000000001."
    )


def test_sms_basico():
    evento = leer_evento_sms("almuerzo.json")
    resultado = sinpe_sms.parsear(evento["body"], evento["received_at"])

    assert resultado.avisos == []
    tx = resultado.transacciones[0]
    assert tx.llave_unica == "sinpe:2026102215283000000000001"
    assert tx.fecha_hora == "2026-10-22T15:28:41-06:00"
    assert tx.monto_centimos == 250000
    assert tx.moneda == "CRC"
    assert tx.tipo == "gasto"
    assert tx.comercio_o_destinatario == "NOMBRE APELLIDO APELLIDO"
    assert tx.descripcion == "Almuerzo"
    assert tx.cuenta_tipo == "sinpe"


def test_descripcion_con_espacios_y_simbolos_y_hora_en_utc():
    evento = leer_evento_sms("pasaje.json")
    tx = sinpe_sms.parsear(evento["body"], evento["received_at"]).transacciones[0]

    assert tx.descripcion == "Pasaje bus #2 (ida)"
    assert tx.monto_centimos == 1234550
    assert tx.comercio_o_destinatario == "PERSONA DE PRUEBA UNO"
    # Fecha del comprobante (23/10) + hora de recepción convertida a CR (13:15Z -> 07:15).
    assert tx.fecha_hora == "2026-10-23T07:15:09-06:00"


def test_descripcion_sin_asteriscos():
    tx = sinpe_sms.parsear(_cuerpo(resto="Cena con amigos"), RECIBIDO).transacciones[0]
    assert tx.descripcion == "Cena con amigos"


def test_descripcion_solo_asteriscos_queda_vacia():
    tx = sinpe_sms.parsear(_cuerpo(resto="**************"), RECIBIDO).transacciones[0]
    assert tx.descripcion is None


def test_cuerpo_con_saltos_de_linea():
    cuerpo = _cuerpo().replace(" por ", "\npor ")
    tx = sinpe_sms.parsear(cuerpo, RECIBIDO).transacciones[0]
    assert tx.comercio_o_destinatario == "NOMBRE APELLIDO APELLIDO"


def test_moneda_desconocida_queda_pendiente():
    resultado = sinpe_sms.parsear(_cuerpo(moneda="Euros"), RECIBIDO)
    assert resultado.transacciones[0].moneda is None
    assert resultado.transacciones[0].estado == "pendiente"
    assert len(resultado.avisos) == 1


def test_sms_no_reconocido_no_expone_contenido():
    cuerpo = "Su codigo de verificacion es 123456 para NOMBRE APELLIDO"
    with pytest.raises(ErrorParseo) as error:
        sinpe_sms.parsear(cuerpo, RECIBIDO)
    assert "NOMBRE" not in str(error.value)
    assert "123456" not in str(error.value)


def test_recibido_sin_zona_horaria_es_error():
    with pytest.raises(ErrorParseo):
        sinpe_sms.parsear(_cuerpo(), "2026-10-22T15:28:41")


def test_comprobante_con_fecha_invalida_es_error():
    cuerpo = _cuerpo().replace("2026102215283000000000001", "2026139915283000000000001")
    with pytest.raises(ErrorParseo):
        sinpe_sms.parsear(cuerpo, RECIBIDO)
