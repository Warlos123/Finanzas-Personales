"""Conversión entre valores de la base y lo que se muestra o se escribe en formularios."""

import re
from datetime import date, datetime

from finanzas.parsers.base import ErrorParseo, monto_a_centimos
from finanzas.tiempo import ZONA_CR

SIMBOLOS = {"CRC": "₡", "USD": "$"}
_PATRON_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def formatear_monto(centimos: int | None, moneda: str | None = "CRC") -> str:
    """250000, 'CRC' -> '₡2,500.00'. Moneda desconocida -> '2,500.00 (?)'."""
    if centimos is None:
        return ""
    signo = ""
    if centimos < 0:
        signo = "-"
        centimos = -centimos
    texto = f"{centimos // 100:,}.{centimos % 100:02d}"
    simbolo = SIMBOLOS.get(moneda)
    if simbolo is None:
        return f"{signo}{texto} (?)"
    return f"{signo}{simbolo}{texto}"


def monto_desde_texto(texto: str) -> int:
    """'₡ 12,345.5' -> 1234550. Lanza ValueError si no es un monto válido."""
    limpio = texto.replace("₡", "").replace("$", "").replace(" ", "")
    try:
        return monto_a_centimos(limpio)
    except ErrorParseo:
        raise ValueError("Monto inválido: usa coma de miles y punto decimal (ej. 12,500.50)") from None


def centimos_a_texto(centimos: int) -> str:
    """Para precargar formularios: 1234550 -> '12345.50'."""
    return f"{centimos // 100}.{centimos % 100:02d}"


def fecha_desde_formulario(texto: str) -> str:
    """'2026-10-26' o '2026-10-26T08:43' (hora de CR) -> ISO 8601 con offset."""
    texto = texto.strip()
    try:
        if len(texto) == 10:
            valor = datetime.combine(date.fromisoformat(texto), datetime.min.time())
        else:
            valor = datetime.fromisoformat(texto)
    except ValueError:
        raise ValueError("Fecha inválida") from None
    return valor.replace(tzinfo=ZONA_CR).isoformat()


def fecha_a_formulario(iso: str) -> str:
    """ISO con offset -> valor para <input type="datetime-local"> en hora de CR."""
    return datetime.fromisoformat(iso).astimezone(ZONA_CR).strftime("%Y-%m-%dT%H:%M")


def fecha_corta(iso: str) -> str:
    """ISO -> '26/10 08:43' en hora de CR."""
    return datetime.fromisoformat(iso).astimezone(ZONA_CR).strftime("%d/%m %H:%M")


def mes_valido(texto: str | None) -> bool:
    return texto is not None and _PATRON_MES.match(texto) is not None


def mes_de(dia: date) -> str:
    return f"{dia.year:04d}-{dia.month:02d}"


def mes_desplazado(mes: str, delta: int) -> str:
    """'2026-01', -1 -> '2025-12'."""
    anio = int(mes[:4])
    numero = int(mes[5:]) - 1 + delta
    anio = anio + numero // 12
    numero = numero % 12
    return f"{anio:04d}-{numero + 1:02d}"


def rango_mes(mes: str) -> tuple[str, str]:
    """Límites para comparar con `fecha_hora` ISO: fecha_hora >= inicio AND fecha_hora < fin."""
    return mes, mes_desplazado(mes, 1)
