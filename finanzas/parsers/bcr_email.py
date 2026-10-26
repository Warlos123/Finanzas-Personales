"""Parser del correo "BCR Tarjetas" (tabla "Detalle de Transacciones").

Las columnas se ubican por el texto del encabezado, no por posición. Si una
fila aprobada no se puede interpretar, falla el correo completo para que
quede marcado como error y se reprocese tras arreglar el parser.
"""

import re
from datetime import datetime
from html.parser import HTMLParser

from finanzas.parsers.base import (
    ErrorParseo,
    ResultadoParseo,
    TransaccionParseada,
    detectar_moneda,
    monto_a_centimos,
    normalizar,
)
from finanzas.tiempo import ZONA_CR

_PATRON_TARJETA = re.compile(r"\*{4}-\*{4}-\*{4}-(\d{4})")
_COLUMNAS = ("fecha", "autorizacion", "noreferencia", "monto", "moneda", "comercio", "estado")
# Etiquetas que separan palabras dentro de una celda.
_SEPARADORES = ("br", "p", "div")


class _ExtractorTablas(HTMLParser):
    """Junta el texto visible y las filas de cada tabla. Soporta tablas anidadas
    y etiquetas `td`/`tr` sin cerrar."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.texto = []
        self.tablas = []
        self._pila = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._pila.append({"filas": [], "fila": None, "celda": None})
            return
        if not self._pila:
            return
        tabla = self._pila[-1]
        if tag == "tr":
            self._cerrar_fila(tabla)
            tabla["fila"] = []
        elif tag == "td" or tag == "th":
            self._cerrar_celda(tabla)
            if tabla["fila"] is None:
                tabla["fila"] = []
            tabla["celda"] = []
        elif tag in _SEPARADORES and tabla["celda"] is not None:
            tabla["celda"].append(" ")

    def handle_endtag(self, tag):
        if not self._pila:
            return
        tabla = self._pila[-1]
        if tag == "table":
            self._cerrar_fila(tabla)
            self.tablas.append(self._pila.pop()["filas"])
        elif tag == "tr":
            self._cerrar_fila(tabla)
        elif tag == "td" or tag == "th":
            self._cerrar_celda(tabla)

    def handle_data(self, data):
        self.texto.append(data)
        if self._pila and self._pila[-1]["celda"] is not None:
            self._pila[-1]["celda"].append(data)

    def _cerrar_celda(self, tabla):
        if tabla["celda"] is None:
            return
        tabla["fila"].append(" ".join("".join(tabla["celda"]).split()))
        tabla["celda"] = None

    def _cerrar_fila(self, tabla):
        self._cerrar_celda(tabla)
        if tabla["fila"] is not None:
            tabla["filas"].append(tabla["fila"])
            tabla["fila"] = None


def _clave_encabezado(texto: str) -> str:
    """'No.Referencia' -> 'noreferencia', 'Autorización' -> 'autorizacion'."""
    return re.sub(r"[^a-z0-9]", "", normalizar(texto))


def _indices_encabezado(fila: list[str]) -> dict[str, int] | None:
    claves = []
    for i in range(len(fila)):
        claves.append(_clave_encabezado(fila[i]))
    indices = {}
    for i in range(len(_COLUMNAS)):
        if _COLUMNAS[i] not in claves:
            return None
        indices[_COLUMNAS[i]] = claves.index(_COLUMNAS[i])
    return indices


def _buscar_detalle(tablas: list[list[list[str]]]):
    """Devuelve (filas_de_datos, indices) de la primera tabla con el encabezado esperado."""
    for t in range(len(tablas)):
        filas = tablas[t]
        for f in range(len(filas)):
            indices = _indices_encabezado(filas[f])
            if indices is None:
                continue
            datos = []
            for d in range(f + 1, len(filas)):
                fila = filas[d]
                if len(fila) != len(filas[f]):
                    continue
                if "".join(fila).strip() == "":
                    continue
                datos.append(fila)
            return datos, indices
    return [], None


def _parsear_fecha(texto: str) -> str:
    try:
        fecha = datetime.strptime(texto.strip(), "%d/%m/%Y %H:%M:%S")
    except ValueError:
        raise ErrorParseo("Fecha con formato no reconocido") from None
    return fecha.replace(tzinfo=ZONA_CR).isoformat()


def _procesar_fila(fila, indices, ultimos4, numero, resultado):
    autorizacion = fila[indices["autorizacion"]].strip()
    referencia = fila[indices["noreferencia"]].strip()
    estado = fila[indices["estado"]].strip()
    if normalizar(estado) != "aprobada":
        resultado.avisos.append(
            f"Fila {numero}: estado '{estado}' no genera transacción (autorización {autorizacion})"
        )
        return
    if autorizacion == "" or referencia == "":
        raise ErrorParseo(f"Fila {numero}: falta autorización o número de referencia")

    texto_moneda = fila[indices["moneda"]].strip()
    moneda = detectar_moneda(texto_moneda)
    estado_tx = "confirmada"
    if moneda is None:
        estado_tx = "pendiente"
        resultado.avisos.append(
            f"Fila {numero}: moneda desconocida '{texto_moneda}', transacción marcada como pendiente"
        )

    resultado.transacciones.append(
        TransaccionParseada(
            llave_unica=f"bcr:{autorizacion}:{referencia}",
            fecha_hora=_parsear_fecha(fila[indices["fecha"]]),
            monto_centimos=monto_a_centimos(fila[indices["monto"]]),
            moneda=moneda,
            tipo="gasto",
            comercio_o_destinatario=fila[indices["comercio"]].strip(),
            descripcion=None,
            estado=estado_tx,
            cuenta_tipo="tarjeta",
            cuenta_ultimos4=ultimos4,
            cuenta_nombre=f"Tarjeta BCR ****{ultimos4}",
        )
    )


def parsear(contenido: str, recibido_en: str) -> ResultadoParseo:
    """`contenido` es el HTML del correo ya decodificado. `recibido_en` no se usa:
    cada fila trae su propia fecha y hora."""
    extractor = _ExtractorTablas()
    extractor.feed(contenido)
    extractor.close()

    tarjeta = _PATRON_TARJETA.search(" ".join(extractor.texto))
    if tarjeta is None:
        raise ErrorParseo("No se encontró el número de tarjeta en el correo")
    ultimos4 = tarjeta.group(1)

    filas, indices = _buscar_detalle(extractor.tablas)
    if indices is None:
        raise ErrorParseo("No se encontró la tabla 'Detalle de Transacciones'")
    if not filas:
        raise ErrorParseo("La tabla de transacciones no tiene filas")

    resultado = ResultadoParseo()
    for i in range(len(filas)):
        _procesar_fila(filas[i], indices, ultimos4, i + 1, resultado)
    return resultado
