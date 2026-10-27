"""Tipo de cambio del dólar, una vez al día, desde la API pública de Hacienda.

Es la única conexión a internet además de Gmail: un GET sin datos del usuario. Se usa el
valor de venta (referencia del BCCR) y se guarda en `settings.tipo_cambio_usd`, el mismo que
se puede editar a mano en "Cuentas y categorías".
"""

import json
import logging
import sqlite3
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation

from finanzas import db, metricas

URL = "https://api.hacienda.go.cr/indicadores/tc/dolar"
AJUSTE_ACTUALIZADO = "tipo_cambio_actualizado"
TIEMPO_LIMITE = 15  # segundos
TAMANO_MAXIMO = 64 * 1024

log = logging.getLogger("finanzas")


def leer_venta(texto: str) -> Decimal:
    """Venta del JSON de Hacienda: {"venta": {"fecha": ..., "valor": 508.12}, "compra": {...}}."""
    try:
        datos = json.loads(texto, parse_float=Decimal)
        valor = Decimal(datos["venta"]["valor"])
    except (ValueError, TypeError, KeyError, InvalidOperation) as error:
        raise ValueError("Respuesta de Hacienda con formato inesperado") from error
    if not valor.is_finite() or valor <= 0:
        raise ValueError("Tipo de cambio de Hacienda inválido")
    return valor.quantize(Decimal("0.01"))


def consultar() -> Decimal:
    pedido = urllib.request.Request(URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=TIEMPO_LIMITE) as respuesta:
        return leer_venta(respuesta.read(TAMANO_MAXIMO).decode("utf-8"))


def actualizar(conn: sqlite3.Connection, ahora: datetime) -> Decimal | None:
    """Consulta Hacienda si hoy todavía no se hizo. Devuelve el valor guardado o None.

    Si falla (red, formato), no guarda nada: la siguiente corrida del timer lo vuelve a intentar.
    """
    ultima = db.leer_ajuste(conn, AJUSTE_ACTUALIZADO, "")
    if ultima[:10] == ahora.date().isoformat():
        return None
    valor = consultar()
    with conn:
        db.guardar_ajuste(conn, metricas.AJUSTE_TIPO_CAMBIO, valor)
        db.guardar_ajuste(conn, AJUSTE_ACTUALIZADO, ahora.isoformat(timespec="seconds"))
    log.info("Tipo de cambio actualizado: %s", valor)
    return valor
