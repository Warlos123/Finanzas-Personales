"""Detección de suscripciones: cobros con tarjeta al mismo comercio, de monto parecido, cerca de
una vez al mes.

Criterios (últimos DIAS_VENTANA días): al menos MINIMO_COBROS cobros en otros tantos meses
distintos; intervalo típico (mediana) entre 25 y 35 días; el mayor monto no supera al menor en más
de 25%; el último cobro fue hace DIAS_ACTIVA días o menos. Los SINPE no cuentan.
"""

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from finanzas.tiempo import ZONA_CR

DIAS_VENTANA = 400
MINIMO_COBROS = 3
INTERVALO_MINIMO = 25
INTERVALO_MAXIMO = 35
VARIACION_MAXIMA = 1.25
DIAS_ACTIVA = 45


@dataclass
class Suscripcion:
    comercio: str
    moneda: str
    monto_tipico: int
    cobros: int
    ultimo_cobro: date
    proximo_cobro: date


def _agrupar(filas: list) -> dict:
    """(comercio, moneda) -> lista de (fecha, monto) en orden de fecha."""
    grupos = {}
    for i in range(len(filas)):
        clave = (filas[i]["comercio_o_destinatario"], filas[i]["moneda"])
        if clave not in grupos:
            grupos[clave] = []
        fecha = datetime.fromisoformat(filas[i]["fecha_hora"]).astimezone(ZONA_CR).date()
        grupos[clave].append((fecha, filas[i]["monto_centimos"]))
    return grupos


def _evaluar(comercio: str, moneda: str, cobros: list, hoy: date) -> Suscripcion | None:
    if len(cobros) < MINIMO_COBROS:
        return None
    meses = set()
    montos = []
    intervalos = []
    for i in range(len(cobros)):
        meses.add((cobros[i][0].year, cobros[i][0].month))
        montos.append(cobros[i][1])
        if i > 0:
            intervalos.append((cobros[i][0] - cobros[i - 1][0]).days)
    if len(meses) < MINIMO_COBROS:
        return None
    tipico = statistics.median(intervalos)
    if tipico < INTERVALO_MINIMO or tipico > INTERVALO_MAXIMO:
        return None
    if min(montos) <= 0 or max(montos) > VARIACION_MAXIMA * min(montos):
        return None
    ultimo = cobros[-1][0]
    if (hoy - ultimo).days > DIAS_ACTIVA:
        return None
    return Suscripcion(
        comercio=comercio,
        moneda=moneda,
        monto_tipico=int(statistics.median(montos)),
        cobros=len(cobros),
        ultimo_cobro=ultimo,
        proximo_cobro=ultimo + timedelta(days=round(tipico)),
    )


def detectar(conn: sqlite3.Connection, hoy: date) -> list[Suscripcion]:
    desde = datetime.combine(hoy - timedelta(days=DIAS_VENTANA), datetime.min.time(), tzinfo=ZONA_CR)
    filas = conn.execute(
        """SELECT t.comercio_o_destinatario, t.moneda, t.monto_centimos, t.fecha_hora
           FROM transactions t LEFT JOIN accounts a ON a.id = t.cuenta_id
           WHERE t.tipo = 'gasto' AND t.estado != 'ignorada' AND t.moneda IS NOT NULL
             AND t.comercio_o_destinatario IS NOT NULL AND (a.tipo IS NULL OR a.tipo != 'sinpe')
             AND t.fecha_hora >= ?
           ORDER BY t.fecha_hora""",
        (desde.isoformat(),),
    ).fetchall()
    grupos = _agrupar(filas)
    claves = list(grupos.keys())
    encontradas = []
    for i in range(len(claves)):
        suscripcion = _evaluar(claves[i][0], claves[i][1], grupos[claves[i]], hoy)
        if suscripcion is not None:
            encontradas.append(suscripcion)
    encontradas.sort(key=lambda s: s.proximo_cobro)
    return encontradas
