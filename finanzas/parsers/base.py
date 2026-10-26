"""Tipos y utilidades compartidas por los parsers.

Los mensajes de error y avisos nunca incluyen el contenido crudo ni nombres
de destinatarios (datos personales de terceros).
"""

import re
import unicodedata
from dataclasses import dataclass, field


class ErrorParseo(Exception):
    """El evento no se pudo interpretar. Se guarda como `error` para reprocesarlo luego."""


@dataclass
class TransaccionParseada:
    llave_unica: str
    fecha_hora: str  # ISO 8601 con offset
    monto_centimos: int
    moneda: str | None  # 'CRC' | 'USD' | None si no se reconoció
    tipo: str
    comercio_o_destinatario: str
    descripcion: str | None
    estado: str  # 'confirmada' | 'pendiente'
    cuenta_tipo: str
    cuenta_ultimos4: str | None
    cuenta_nombre: str


@dataclass
class ResultadoParseo:
    transacciones: list[TransaccionParseada] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    letras = []
    for i in range(len(descompuesto)):
        if not unicodedata.combining(descompuesto[i]):
            letras.append(descompuesto[i])
    return " ".join("".join(letras).lower().split())


_PATRON_MONTO = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$")


def monto_a_centimos(texto: str) -> int:
    """'2,500.00' -> 250000. Coma de miles y punto decimal."""
    limpio = texto.strip()
    if _PATRON_MONTO.match(limpio) is None:
        raise ErrorParseo("Monto con formato no reconocido")
    partes = limpio.replace(",", "").split(".")
    centimos = int(partes[0]) * 100
    if len(partes) == 2:
        centimos = centimos + int(partes[1].ljust(2, "0"))
    return centimos


def detectar_moneda(texto: str) -> str | None:
    """'COLON COSTA RICA', 'Colones' -> CRC; textos con 'dolar' -> USD; otro -> None."""
    normalizado = normalizar(texto)
    if "colon" in normalizado:
        return "CRC"
    if "dolar" in normalizado:
        return "USD"
    return None
