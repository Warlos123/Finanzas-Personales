"""Datos y geometría de los gráficos (SVG armado en el servidor, sin JavaScript).

- Gasto por mes: columnas de los últimos 12 meses que terminan en el mes elegido; ese mes va
  resaltado y con su valor; el resto en gris. Ejes con números redondos y compactos (₡250K).
- Gastos más grandes: reutiliza metricas.gastos_mas_grandes (se dibuja con barras HTML).
Todo en colones, con las mismas reglas que el dashboard (sin transferencias ni reembolsables).
"""

import math
import sqlite3
from dataclasses import dataclass, field

from finanzas import formato, metricas

MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

# Lienzo del gráfico de columnas (unidades del viewBox).
ANCHO = 720
ALTO_PLOT = 220
MARGEN_IZQ = 64
MARGEN_DER = 12
MARGEN_SUP = 24
BANDA_EJE_X = 40
GROSOR_MAXIMO = 24
RADIO_PUNTA = 4


@dataclass
class Columna:
    mes: str
    gasto: int  # céntimos
    x: float
    ancho: float
    trazo: str  # path SVG: punta redondeada arriba, recta en la base
    etiqueta: str  # "oct"
    anio: str  # "2026" solo en enero y en la primera columna
    resaltada: bool
    texto_valor: str
    centro: float
    y_valor: float


@dataclass
class Marca:
    y: float
    texto: str


@dataclass
class GraficoMeses:
    columnas: list = field(default_factory=list)
    marcas: list = field(default_factory=list)
    ancho: int = ANCHO
    alto: int = MARGEN_SUP + ALTO_PLOT + BANDA_EJE_X
    base: float = MARGEN_SUP + ALTO_PLOT
    izquierda: int = MARGEN_IZQ
    derecha: int = ANCHO - MARGEN_DER


def compacto(centimos: int) -> str:
    """Colones compactos para ejes: ₡0, ₡250K, ₡1.2M."""
    colones = centimos / 100
    if colones >= 1_000_000:
        texto = f"{colones / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"₡{texto}M"
    if colones >= 1_000:
        return f"₡{colones / 1_000:.0f}K"
    return f"₡{colones:.0f}"


def paso_redondo(maximo: int, marcas: int = 4) -> int:
    """Paso de 1, 2, 2.5 o 5 × 10^k que cubre `maximo` con unas `marcas` divisiones."""
    if maximo <= 0:
        return 100_000  # ₡1,000
    crudo = maximo / marcas
    potencia = 10 ** math.floor(math.log10(crudo))
    factores = (1, 2, 2.5, 5, 10)
    for i in range(len(factores)):
        paso = factores[i] * potencia
        if paso >= crudo:
            return int(paso)
    return int(10 * potencia)


def gasto_por_mes(conn: sqlite3.Connection, mes_final: str, cantidad: int = 12) -> list[tuple[str, int]]:
    """[(mes, gasto en céntimos de colón)] de los `cantidad` meses que terminan en `mes_final`."""
    cambio = metricas.tipo_cambio(conn)
    primero = formato.mes_desplazado(mes_final, -(cantidad - 1))
    _, fin = formato.rango_mes(mes_final)
    filas = conn.execute(
        """SELECT substr(fecha_hora, 1, 7) AS mes, moneda, SUM(monto_centimos) AS total
           FROM transactions
           WHERE tipo = 'gasto' AND estado != 'ignorada' AND moneda IS NOT NULL
             AND fecha_hora >= ? AND fecha_hora < ?
           GROUP BY mes, moneda""",
        (primero, fin),
    ).fetchall()
    totales = {}
    for i in range(len(filas)):
        monto = metricas.en_colones(filas[i]["total"], filas[i]["moneda"], cambio)
        if monto is not None:
            totales[filas[i]["mes"]] = totales.get(filas[i]["mes"], 0) + monto
    resultado = []
    for i in range(cantidad):
        mes = formato.mes_desplazado(primero, i)
        resultado.append((mes, totales.get(mes, 0)))
    return resultado


def _trazo_columna(x: float, y: float, ancho: float, base: float) -> str:
    alto = base - y
    radio = min(RADIO_PUNTA, alto, ancho / 2)
    if alto <= 0:
        return ""
    return (
        f"M{x:.1f},{base:.1f} V{y + radio:.1f} Q{x:.1f},{y:.1f} {x + radio:.1f},{y:.1f} "
        f"H{x + ancho - radio:.1f} Q{x + ancho:.1f},{y:.1f} {x + ancho:.1f},{y + radio:.1f} "
        f"V{base:.1f} Z"
    )


def grafico_meses(datos: list[tuple[str, int]], mes_resaltado: str) -> GraficoMeses:
    grafico = GraficoMeses()
    maximo = 0
    for i in range(len(datos)):
        maximo = max(maximo, datos[i][1])
    paso = paso_redondo(maximo)
    tope = paso * max(1, math.ceil(maximo / paso))

    divisiones = tope // paso
    for i in range(divisiones + 1):
        valor = paso * i
        y = grafico.base - ALTO_PLOT * valor / tope
        grafico.marcas.append(Marca(y=y, texto=compacto(valor)))

    franja = (grafico.derecha - grafico.izquierda) / len(datos)
    ancho = min(GROSOR_MAXIMO, franja * 0.6)
    for i in range(len(datos)):
        mes, gasto = datos[i]
        x = grafico.izquierda + franja * i + (franja - ancho) / 2
        y = grafico.base - ALTO_PLOT * gasto / tope
        anio = ""
        if i == 0 or mes.endswith("-01"):
            anio = mes[:4]
        grafico.columnas.append(Columna(
            mes=mes, gasto=gasto, x=x, ancho=ancho, trazo=_trazo_columna(x, y, ancho, grafico.base),
            etiqueta=MESES_CORTOS[int(mes[5:]) - 1], anio=anio, resaltada=mes == mes_resaltado,
            texto_valor=compacto(gasto), centro=x + ancho / 2, y_valor=y - 6,
        ))
    return grafico
