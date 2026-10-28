"""Estado de cuenta del BCR (PDF de la cuenta de ahorros) para reconciliar.

- El PDF se convierte a texto con `pdftotext -layout` (paquete poppler); el PDF no se guarda.
- Débito y crédito solo se distinguen por la columna: se compara dónde termina cada monto con
  el punto medio entre los encabezados "Monto Débito" y "Monto Crédito" de la misma página.
- La lectura se valida con los totales del propio estado (débitos, créditos y saldo final);
  si no cuadra, se rechaza el archivo completo.
Los errores nunca incluyen el contenido del estado.
"""

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from finanzas.parsers.base import ErrorParseo, monto_a_centimos

_MONTO = r"\d{1,3}(?:,\d{3})*\.\d\d"
_FILA = re.compile(
    r"^\s*(\d\d/\d\d/\d\d)\s+\d\d/\d\d/\d\d\s+(?:(\d{4})\s+)?(\d+)\s+(\S.*?)\s{2,}(" + _MONTO + r")\s*$"
)
_INICIO_FILA = re.compile(r"^\s*\d\d/\d\d/\d\d\s")
_DEBITO = re.compile(r"Monto D.bito")
_CREDITO = re.compile(r"Monto Cr.dito")
_PERIODO = re.compile(r"(\d\d)/(\d\d)/(\d{4})\s+al\s+(\d\d)/(\d\d)/(\d{4})")
_SALDO_ANTERIOR = re.compile(r"Saldo Anterior\s*:\s*(" + _MONTO + ")")
_SALDO_FINAL = re.compile(r"Saldo Final\s*:\s*(" + _MONTO + ")")
_TOTALES = re.compile(r"D.bitos\s*/\s*Cr.ditos\s*:\s*(" + _MONTO + r")\s+(" + _MONTO + ")")
_COMERCIO = re.compile(r"^\S+\s+\+\d{3}(.+)$")
_TELEFONO = re.compile(r"\b\d{8}-")

TIPOS_SINPE = ("MONEDERO SINPE MOVIL", "SINPE MOVIL OTRA ENT")
# Plata que se mueve entre cuentas propias: no es gasto ni ingreso.
PREFIJOS_INTERNOS = ("EMISION CDP", "CANC CDP", "TRAN CTA AH TAR VIRT")


@dataclass
class Movimiento:
    fecha: str  # AAAA-MM-DD (fecha del movimiento, no la contable)
    tarjeta: str | None  # últimos 4 en las compras con tarjeta
    documento: str  # en compras = autorización del correo sin ceros a la izquierda
    tipo: str  # "COMPRAS EN COMERCIOS", "TRANSFERENC BANCOBCR", ...
    detalle: str
    monto_centimos: int
    credito: bool

    @property
    def clase(self) -> str:
        """'compra', 'sinpe', 'interno' u 'otro'."""
        if self.tipo == "COMPRAS EN COMERCIOS" and self.tarjeta is not None:
            return "compra"
        if self.tipo in TIPOS_SINPE:
            return "sinpe"
        for i in range(len(PREFIJOS_INTERNOS)):
            if self.tipo.startswith(PREFIJOS_INTERNOS[i]):
                return "interno"
        return "otro"

    @property
    def texto(self) -> str | None:
        """Comercio en compras; descripción del SINPE sin el teléfono ni el relleno; si no, el detalle."""
        if self.clase == "compra":
            coincidencia = _COMERCIO.match(self.detalle)
            if coincidencia is not None:
                return coincidencia.group(1).strip()
            return self.detalle
        if self.clase == "sinpe":
            limpio = _TELEFONO.sub("", self.detalle).rstrip("*").strip()
            if limpio.startswith("0-") and limpio.endswith("-0"):
                limpio = limpio[2:-2].strip("_ ")
            if limpio == "" or limpio == "Sin Descripcion":
                return None
            return limpio
        return self.detalle

    @property
    def llave(self) -> str:
        return f"estado:{self.fecha}:{self.documento}:{self.monto_centimos}"


@dataclass
class EstadoCuenta:
    moneda: str
    desde: str  # AAAA-MM-DD
    hasta: str
    saldo_anterior: int
    saldo_final: int
    debitos: int
    creditos: int
    movimientos: list = field(default_factory=list)


def texto_de_pdf(contenido: bytes) -> str:
    """Texto del PDF con `pdftotext -layout`. Lanza ValueError con un mensaje para mostrar."""
    if not contenido.startswith(b"%PDF"):
        raise ValueError("El archivo no es un PDF")
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "estado.pdf"
        ruta.write_bytes(contenido)
        try:
            proceso = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(ruta), "-"],
                capture_output=True, timeout=60, check=False,
            )
        except FileNotFoundError:
            raise ValueError("Falta pdftotext: instala el paquete poppler") from None
    if proceso.returncode != 0:
        raise ValueError("No se pudo leer el PDF")
    return proceso.stdout.decode("utf-8", errors="replace")


def _fecha(dia: str, mes: str, anio: str) -> str:
    if len(anio) == 2:
        anio = "20" + anio
    return f"{anio}-{mes}-{dia}"


def _monto(texto: str) -> int:
    try:
        return monto_a_centimos(texto)
    except ErrorParseo:
        raise ValueError("Monto ilegible en el estado de cuenta") from None


def _buscar(patron: re.Pattern, texto: str, que: str) -> re.Match:
    coincidencia = patron.search(texto)
    if coincidencia is None:
        raise ValueError(f"No se encontró {que} en el estado de cuenta")
    return coincidencia


def leer(texto: str) -> EstadoCuenta:
    """Interpreta el texto de `pdftotext -layout`. Lanza ValueError si el formato no calza o no cuadra."""
    moneda = None
    if re.search(r"\bCOLONES\b", texto):
        moneda = "CRC"
    elif re.search(r"\bD.LARES\b", texto):
        moneda = "USD"
    if moneda is None:
        raise ValueError("No se reconoció la moneda de la cuenta")
    periodo = _buscar(_PERIODO, texto, "el período")
    totales = _buscar(_TOTALES, texto, "el total de débitos y créditos")
    estado = EstadoCuenta(
        moneda=moneda,
        desde=_fecha(periodo.group(1), periodo.group(2), periodo.group(3)),
        hasta=_fecha(periodo.group(4), periodo.group(5), periodo.group(6)),
        saldo_anterior=_monto(_buscar(_SALDO_ANTERIOR, texto, "el saldo anterior").group(1)),
        saldo_final=_monto(_buscar(_SALDO_FINAL, texto, "el saldo final").group(1)),
        debitos=_monto(totales.group(1)),
        creditos=_monto(totales.group(2)),
    )

    limite = None  # columna que separa débitos de créditos en la página actual
    lineas = texto.split("\n")
    for i in range(len(lineas)):
        linea = lineas[i]
        debito = _DEBITO.search(linea)
        credito = _CREDITO.search(linea)
        if debito is not None and credito is not None:
            limite = (debito.end() + credito.end()) / 2
            continue
        if _INICIO_FILA.match(linea) is None:
            continue
        fila = _FILA.match(linea)
        if fila is None or limite is None:
            raise ValueError(f"Línea {i + 1} del estado de cuenta con formato no reconocido")
        dia, mes, anio = fila.group(1).split("/")
        tipo = fila.group(4)
        detalle = ""
        if " - " in tipo:
            tipo, detalle = tipo.split(" - ", 1)
        estado.movimientos.append(Movimiento(
            fecha=_fecha(dia, mes, anio), tarjeta=fila.group(2), documento=fila.group(3),
            tipo=tipo.strip(), detalle=detalle.strip(), monto_centimos=_monto(fila.group(5)),
            credito=fila.end(5) > limite,
        ))

    suma_debitos = 0
    suma_creditos = 0
    for i in range(len(estado.movimientos)):
        if estado.movimientos[i].credito:
            suma_creditos += estado.movimientos[i].monto_centimos
        else:
            suma_debitos += estado.movimientos[i].monto_centimos
    if suma_debitos != estado.debitos or suma_creditos != estado.creditos:
        raise ValueError("Los movimientos leídos no suman los totales del estado de cuenta")
    if estado.saldo_anterior - estado.debitos + estado.creditos != estado.saldo_final:
        raise ValueError("El saldo final del estado de cuenta no cuadra")
    return estado
