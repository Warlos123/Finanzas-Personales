"""Métricas del dashboard mensual.

- Se excluyen las transacciones ignoradas y las de moneda desconocida.
- Gasto = tipo `gasto`; ingresos = tipo `ingreso`. Transferencias y reembolsables se
  informan aparte y no entran en gasto, balance ni tasa de ahorro.
- Todo se expresa en colones. Los dólares se convierten con `settings.tipo_cambio_usd`
  si está definido; si no, se informan aparte y no entran en los totales.
"""

import calendar
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from finanzas import db
from finanzas.formato import mes_desplazado, rango_mes

AJUSTE_TIPO_CAMBIO = "tipo_cambio_usd"
TOP = 10
SIN_CATEGORIA = "Sin categoría"


@dataclass
class ResumenMes:
    mes: str
    gasto: int = 0
    ingresos: int = 0
    ingresos_extraordinarios: int = 0
    transferencias: int = 0
    reembolsables: int = 0
    usd_gasto_sin_convertir: int = 0
    usd_ingresos_sin_convertir: int = 0
    por_categoria: list = field(default_factory=list)  # (nombre, monto, porcentaje)
    top_comercios: list = field(default_factory=list)  # (nombre, monto, cantidad)
    top_destinatarios: list = field(default_factory=list)
    dias_mes: int = 0
    dias_transcurridos: int = 0
    es_mes_actual: bool = False
    gasto_anterior: int = 0
    ingresos_anterior: int = 0

    @property
    def balance(self) -> int:
        return self.ingresos - self.gasto

    @property
    def tasa_ahorro(self) -> float | None:
        if self.ingresos <= 0:
            return None
        return self.balance / self.ingresos

    @property
    def promedio_diario(self) -> int:
        if self.dias_transcurridos == 0:
            return 0
        return self.gasto // self.dias_transcurridos

    @property
    def proyeccion(self) -> int:
        """Gasto esperado al cierre del mes al ritmo actual."""
        if not self.es_mes_actual:
            return self.gasto
        return self.promedio_diario * self.dias_mes

    @property
    def variacion_gasto(self) -> float | None:
        """Proyección (mes actual) o gasto (meses cerrados) contra el gasto del mes anterior."""
        if self.gasto_anterior <= 0:
            return None
        return (self.proyeccion - self.gasto_anterior) / self.gasto_anterior


def tipo_cambio(conn: sqlite3.Connection) -> Decimal | None:
    valor = db.leer_ajuste(conn, AJUSTE_TIPO_CAMBIO)
    if not valor:
        return None
    try:
        cambio = Decimal(valor)
    except InvalidOperation:
        return None
    if cambio <= 0:
        return None
    return cambio


def en_colones(monto: int, moneda: str, cambio: Decimal | None) -> int | None:
    """Céntimos de colón, o None si es USD y no hay tipo de cambio."""
    return _en_colones(monto, moneda, cambio)


def _en_colones(monto: int, moneda: str, cambio: Decimal | None) -> int | None:
    if moneda == "CRC":
        return monto
    if cambio is None:
        return None
    return int((Decimal(monto) * cambio).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _filas_del_mes(conn: sqlite3.Connection, mes: str) -> list:
    inicio, fin = rango_mes(mes)
    return conn.execute(
        """SELECT t.monto_centimos, t.moneda, t.tipo, t.extraordinario, t.comercio_o_destinatario,
                  c.nombre AS categoria, a.tipo AS cuenta_tipo
           FROM transactions t
           LEFT JOIN categories c ON c.id = t.categoria_id
           LEFT JOIN accounts a ON a.id = t.cuenta_id
           WHERE t.fecha_hora >= ? AND t.fecha_hora < ?
             AND t.estado != 'ignorada' AND t.moneda IS NOT NULL""",
        (inicio, fin),
    ).fetchall()


def _sumar(acumulado: dict, clave: str, monto: int) -> None:
    if clave not in acumulado:
        acumulado[clave] = [0, 0]
    acumulado[clave][0] += monto
    acumulado[clave][1] += 1


def _ordenados(acumulado: dict, limite: int | None) -> list:
    claves = list(acumulado.keys())
    lista = []
    for i in range(len(claves)):
        lista.append((claves[i], acumulado[claves[i]][0], acumulado[claves[i]][1]))
    lista.sort(key=lambda elemento: elemento[1], reverse=True)
    if limite is not None:
        lista = lista[:limite]
    return lista


def _acumular(resumen: ResumenMes, filas: list, cambio: Decimal | None) -> None:
    categorias = {}
    comercios = {}
    destinatarios = {}
    for i in range(len(filas)):
        fila = filas[i]
        monto = _en_colones(fila["monto_centimos"], fila["moneda"], cambio)
        tipo = fila["tipo"]
        if monto is None:
            if tipo == "gasto":
                resumen.usd_gasto_sin_convertir += fila["monto_centimos"]
            elif tipo == "ingreso":
                resumen.usd_ingresos_sin_convertir += fila["monto_centimos"]
            continue
        if tipo == "ingreso":
            resumen.ingresos += monto
            if fila["extraordinario"]:
                resumen.ingresos_extraordinarios += monto
        elif tipo == "transferencia":
            resumen.transferencias += monto
        elif tipo == "reembolsable":
            resumen.reembolsables += monto
        elif tipo == "gasto":
            resumen.gasto += monto
            categoria = fila["categoria"]
            if categoria is None:
                categoria = SIN_CATEGORIA
            _sumar(categorias, categoria, monto)
            nombre = fila["comercio_o_destinatario"]
            if not nombre:
                nombre = "(sin nombre)"
            if fila["cuenta_tipo"] == "sinpe":
                _sumar(destinatarios, nombre, monto)
            else:
                _sumar(comercios, nombre, monto)

    por_categoria = _ordenados(categorias, None)
    for i in range(len(por_categoria)):
        nombre, monto, _ = por_categoria[i]
        porcentaje = 0.0
        if resumen.gasto > 0:
            porcentaje = monto / resumen.gasto
        resumen.por_categoria.append((nombre, monto, porcentaje))
    resumen.top_comercios = _ordenados(comercios, TOP)
    resumen.top_destinatarios = _ordenados(destinatarios, TOP)


def resumen_mes(conn: sqlite3.Connection, mes: str, hoy: date) -> ResumenMes:
    cambio = tipo_cambio(conn)
    resumen = ResumenMes(mes=mes)
    _acumular(resumen, _filas_del_mes(conn, mes), cambio)

    anterior = ResumenMes(mes=mes_desplazado(mes, -1))
    _acumular(anterior, _filas_del_mes(conn, anterior.mes), cambio)
    resumen.gasto_anterior = anterior.gasto
    resumen.ingresos_anterior = anterior.ingresos

    anio = int(mes[:4])
    numero = int(mes[5:])
    resumen.dias_mes = calendar.monthrange(anio, numero)[1]
    if (anio, numero) == (hoy.year, hoy.month):
        resumen.es_mes_actual = True
        resumen.dias_transcurridos = hoy.day
    elif (anio, numero) < (hoy.year, hoy.month):
        resumen.dias_transcurridos = resumen.dias_mes
    return resumen


@dataclass
class Presupuesto:
    categoria_id: int
    nombre: str
    presupuesto: int
    gastado: int

    @property
    def proporcion(self) -> float:
        if self.presupuesto <= 0:
            return 0.0
        return self.gastado / self.presupuesto

    @property
    def nivel(self) -> str:
        """'excedido' desde 100%, 'alerta' desde 80%, si no 'ok'."""
        if self.proporcion >= 1.0:
            return "excedido"
        if self.proporcion >= 0.8:
            return "alerta"
        return "ok"


def estado_presupuestos(conn: sqlite3.Connection, mes: str) -> list[Presupuesto]:
    """Gasto del mes contra el presupuesto de cada categoría que tenga uno.
    El gasto de una categoría incluye el de sus subcategorías directas."""
    cambio = tipo_cambio(conn)
    inicio, fin = rango_mes(mes)
    padres = {}
    categorias = conn.execute("SELECT id, padre_id FROM categories").fetchall()
    for i in range(len(categorias)):
        padres[categorias[i]["id"]] = categorias[i]["padre_id"]

    gastado = {}
    filas = conn.execute(
        """SELECT categoria_id, moneda, SUM(monto_centimos) AS total FROM transactions
           WHERE tipo = 'gasto' AND estado != 'ignorada' AND moneda IS NOT NULL
             AND categoria_id IS NOT NULL AND fecha_hora >= ? AND fecha_hora < ?
           GROUP BY categoria_id, moneda""",
        (inicio, fin),
    ).fetchall()
    for i in range(len(filas)):
        monto = _en_colones(filas[i]["total"], filas[i]["moneda"], cambio)
        if monto is None:
            continue
        categoria = filas[i]["categoria_id"]
        gastado[categoria] = gastado.get(categoria, 0) + monto
        padre = padres.get(categoria)
        if padre is not None:
            gastado[padre] = gastado.get(padre, 0) + monto

    resultado = []
    presupuestos = conn.execute(
        """SELECT b.categoria_id, b.monto_mensual_centimos, c.nombre FROM budgets b
           JOIN categories c ON c.id = b.categoria_id ORDER BY c.nombre"""
    ).fetchall()
    for i in range(len(presupuestos)):
        categoria = presupuestos[i]["categoria_id"]
        resultado.append(Presupuesto(
            categoria_id=categoria,
            nombre=presupuestos[i]["nombre"],
            presupuesto=presupuestos[i]["monto_mensual_centimos"],
            gastado=gastado.get(categoria, 0),
        ))
    return resultado


@dataclass
class GastoGrande:
    fecha_hora: str
    nombre: str
    categoria: str | None
    monto: int  # en colones (convertido si era USD)
    moneda: str
    monto_original: int


def gastos_mas_grandes(conn: sqlite3.Connection, mes: str, limite: int = 10) -> list[GastoGrande]:
    """Los gastos individuales más grandes del mes, en colones. Sin tipo de cambio, los USD no entran."""
    cambio = tipo_cambio(conn)
    inicio, fin = rango_mes(mes)
    filas = conn.execute(
        """SELECT t.fecha_hora, t.comercio_o_destinatario, t.descripcion, t.monto_centimos, t.moneda,
                  c.nombre AS categoria
           FROM transactions t LEFT JOIN categories c ON c.id = t.categoria_id
           WHERE t.tipo = 'gasto' AND t.estado != 'ignorada' AND t.moneda IS NOT NULL
             AND t.fecha_hora >= ? AND t.fecha_hora < ?""",
        (inicio, fin),
    ).fetchall()
    gastos = []
    for i in range(len(filas)):
        monto = _en_colones(filas[i]["monto_centimos"], filas[i]["moneda"], cambio)
        if monto is None:
            continue
        nombre = filas[i]["comercio_o_destinatario"]
        if not nombre:
            nombre = "(sin nombre)"
        if filas[i]["descripcion"]:
            nombre = f"{nombre} · {filas[i]['descripcion']}"
        gastos.append(GastoGrande(
            fecha_hora=filas[i]["fecha_hora"], nombre=nombre, categoria=filas[i]["categoria"],
            monto=monto, moneda=filas[i]["moneda"], monto_original=filas[i]["monto_centimos"],
        ))
    gastos.sort(key=lambda gasto: gasto.monto, reverse=True)
    return gastos[:limite]
