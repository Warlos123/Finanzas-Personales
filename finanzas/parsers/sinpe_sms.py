"""Parser del SMS de SINPE Móvil enviado (remitente 4066).

Ejemplo: "Ha enviado 2,500.00 Colones a NOMBRE APELLIDO APELLIDO por SINPE Movil,
Almuerzo*********. Comprobante 2026102215283000000000001."

La fecha sale de los primeros 8 dígitos del comprobante (YYYYMMDD) y la hora
de la marca de recepción del SMS.
"""

import re
from datetime import datetime

from finanzas.parsers.base import (
    ErrorParseo,
    ResultadoParseo,
    TransaccionParseada,
    detectar_moneda,
    monto_a_centimos,
)
from finanzas.tiempo import ZONA_CR

_PATRON = re.compile(
    r"^Ha enviado (?P<monto>[\d,]+(?:\.\d{1,2})?) (?P<moneda>\S+) a (?P<destinatario>.+?)"
    r" por SINPE M[oó]vil(?:, (?P<descripcion>.*?))?\**\. Comprobante (?P<comprobante>\d{8,})\.?$"
)


def _fecha_hora(comprobante: str, recibido_en: str) -> str:
    try:
        fecha = datetime.strptime(comprobante[:8], "%Y%m%d").date()
    except ValueError:
        raise ErrorParseo("Comprobante sin fecha válida en sus primeros 8 dígitos") from None
    try:
        recibido = datetime.fromisoformat(recibido_en)
    except ValueError:
        raise ErrorParseo("received_at no es ISO 8601") from None
    if recibido.tzinfo is None:
        raise ErrorParseo("received_at no trae zona horaria")
    hora = recibido.astimezone(ZONA_CR).time().replace(microsecond=0)
    return datetime.combine(fecha, hora, tzinfo=ZONA_CR).isoformat()


def parsear(contenido: str, recibido_en: str) -> ResultadoParseo:
    """`contenido` es el cuerpo del SMS; `recibido_en` su marca de recepción con offset."""
    texto = " ".join(contenido.split())
    coincidencia = _PATRON.match(texto)
    if coincidencia is None:
        raise ErrorParseo("SMS con formato no reconocido")

    comprobante = coincidencia.group("comprobante")
    texto_moneda = coincidencia.group("moneda")
    moneda = detectar_moneda(texto_moneda)
    resultado = ResultadoParseo()
    estado = "confirmada"
    if moneda is None:
        estado = "pendiente"
        resultado.avisos.append(
            f"Moneda desconocida '{texto_moneda}', transacción marcada como pendiente"
        )

    descripcion = coincidencia.group("descripcion")
    if descripcion is not None:
        descripcion = descripcion.strip()
        if descripcion == "":
            descripcion = None

    resultado.transacciones.append(
        TransaccionParseada(
            llave_unica=f"sinpe:{comprobante}",
            fecha_hora=_fecha_hora(comprobante, recibido_en),
            monto_centimos=monto_a_centimos(coincidencia.group("monto")),
            moneda=moneda,
            tipo="gasto",
            comercio_o_destinatario=coincidencia.group("destinatario").strip(),
            descripcion=descripcion,
            estado=estado,
            cuenta_tipo="sinpe",
            cuenta_ultimos4=None,
            cuenta_nombre="SINPE Móvil",
        )
    )
    return resultado
