"""Estado de sincronización y alertas de escritorio.

- Novedades: un solo aviso por corrida si entraron transacciones a la bandeja o eventos que
  no se pudieron interpretar.
- Teléfono: aviso si pasan DIAS_SIN_TELEFONO sin eventos nuevos. Se mide por el último evento
  importado (o, si nunca llegó uno, por la fecha en que se configuró la carpeta). Se avisa una
  sola vez por cada "último evento"; un evento nuevo rearma el aviso.
- Presupuestos: un aviso por categoría al llegar al 80% y otro al pasar el 100% en el mes.
- Gasto atípico: un gasto nuevo mayor a MINIMO_ATIPICO y a VECES_ATIPICO la mediana de su
  categoría (o de todos los gastos si no tiene) en los DIAS_HISTORIA previos; hacen falta al
  menos MUESTRAS_MINIMAS gastos de referencia. Un aviso por corrida.
"""

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from finanzas import db, formato, metricas, movimientos, telefono
from finanzas.notificar import notificar
from finanzas.tiempo import ahora_iso

DIAS_SIN_TELEFONO = 3
AJUSTE_AVISO_TELEFONO = "aviso_telefono_para"
MINIMO_ATIPICO = 2_000_000  # ₡20,000 en céntimos
VECES_ATIPICO = 3
DIAS_HISTORIA = 90
MUESTRAS_MINIMAS = 5


@dataclass
class Conteos:
    bandeja: int
    errores: int


@dataclass
class EstadoSincronizacion:
    ultima_importacion_correo: str | None
    telefono_configurado: bool
    ultimo_evento_telefono: str | None
    dias_sin_telefono: int | None
    telefono_atrasado: bool


def contar(conn: sqlite3.Connection) -> Conteos:
    errores = conn.execute("SELECT COUNT(*) FROM raw_events WHERE estado_parseo = 'error'").fetchone()[0]
    return Conteos(bandeja=movimientos.contar_bandeja(conn), errores=errores)


def avisar_novedades(conn: sqlite3.Connection, antes: Conteos) -> bool:
    """Notifica si la corrida dejó más pendientes o errores que antes. Devuelve si avisó."""
    despues = contar(conn)
    nuevos_pendientes = despues.bandeja - antes.bandeja
    nuevos_errores = despues.errores - antes.errores
    partes = []
    if nuevos_pendientes > 0:
        partes.append(f"{nuevos_pendientes} transacciones nuevas por categorizar")
    if nuevos_errores > 0:
        partes.append(f"{nuevos_errores} eventos que no se pudieron interpretar")
    if not partes:
        return False
    notificar("Finanzas: hay cosas por revisar", "; ".join(partes) + ". Abre la bandeja.")
    return True


def estado(conn: sqlite3.Connection, ahora: datetime) -> EstadoSincronizacion:
    correo = conn.execute(
        "SELECT MAX(fin) FROM import_runs WHERE fuente = 'gmail_bcr' AND fin IS NOT NULL"
    ).fetchone()[0]
    configurado_en = db.leer_ajuste(conn, telefono.AJUSTE_CONFIGURADO_EN)
    ultimo = db.leer_ajuste(conn, telefono.AJUSTE_ULTIMO_EVENTO)
    base = ultimo
    if base is None:
        base = configurado_en
    dias = None
    atrasado = False
    if base is not None:
        dias = (ahora - datetime.fromisoformat(base)).days
        atrasado = dias >= DIAS_SIN_TELEFONO
    return EstadoSincronizacion(
        ultima_importacion_correo=correo,
        telefono_configurado=db.leer_ajuste(conn, telefono.AJUSTE_CARPETA) is not None,
        ultimo_evento_telefono=ultimo,
        dias_sin_telefono=dias,
        telefono_atrasado=atrasado,
    )


def avisar_telefono(conn: sqlite3.Connection, ahora: datetime) -> bool:
    """Notifica una vez si el teléfono lleva DIAS_SIN_TELEFONO o más sin eventos."""
    situacion = estado(conn, ahora)
    if not situacion.telefono_configurado or not situacion.telefono_atrasado:
        return False
    referencia = situacion.ultimo_evento_telefono
    if referencia is None:
        referencia = "nunca"
    if db.leer_ajuste(conn, AJUSTE_AVISO_TELEFONO) == referencia:
        return False
    notificar(
        "Finanzas: el teléfono no sincroniza",
        f"Hace {situacion.dias_sin_telefono} días que no llegan SINPE del teléfono. "
        "Revisa Syncthing y la app Finanzas SMS.",
    )
    with conn:
        db.guardar_ajuste(conn, AJUSTE_AVISO_TELEFONO, referencia)
    return True


def avisar_presupuestos(conn: sqlite3.Connection, hoy) -> int:
    """Un aviso por categoría y umbral (80% y 100%) en el mes en curso. Devuelve cuántos avisó."""
    mes = formato.mes_de(hoy)
    lineas = []
    estados = metricas.estado_presupuestos(conn, mes)
    for i in range(len(estados)):
        presupuesto = estados[i]
        if presupuesto.nivel == "ok":
            continue
        umbral = 80
        if presupuesto.nivel == "excedido":
            umbral = 100
        clave = f"aviso_presupuesto:{mes}:{presupuesto.categoria_id}:{umbral}"
        if db.leer_ajuste(conn, clave) is not None:
            continue
        lineas.append(
            f"{presupuesto.nombre}: {formato.porcentaje(presupuesto.proporcion)} "
            f"({formato.formatear_monto(presupuesto.gastado)} de {formato.formatear_monto(presupuesto.presupuesto)})"
        )
        with conn:
            db.guardar_ajuste(conn, clave, ahora_iso())
    if lineas:
        notificar("Finanzas: presupuesto", "\n".join(lineas))
    return len(lineas)


@dataclass
class GastoAtipico:
    transaccion_id: int
    descripcion: str
    monto: int
    veces: float


def _montos_de_referencia(conn, transaccion, cambio) -> list[int]:
    fecha = datetime.fromisoformat(transaccion["fecha_hora"])
    inicio = (fecha - timedelta(days=DIAS_HISTORIA)).isoformat()
    sql = (
        "SELECT monto_centimos, moneda FROM transactions WHERE tipo = 'gasto' AND estado != 'ignorada' "
        "AND moneda IS NOT NULL AND id != ? AND fecha_hora >= ? AND fecha_hora < ?"
    )
    parametros = [transaccion["id"], inicio, transaccion["fecha_hora"]]
    if transaccion["categoria_id"] is not None:
        sql = sql + " AND categoria_id = ?"
        parametros.append(transaccion["categoria_id"])
    filas = conn.execute(sql, parametros).fetchall()
    montos = []
    for i in range(len(filas)):
        monto = metricas.en_colones(filas[i]["monto_centimos"], filas[i]["moneda"], cambio)
        if monto is not None:
            montos.append(monto)
    return montos


def gastos_atipicos(conn: sqlite3.Connection, creadas_desde: str) -> list[GastoAtipico]:
    """Gastos creados desde `creadas_desde` que se salen de lo normal."""
    cambio = metricas.tipo_cambio(conn)
    nuevas = conn.execute(
        """SELECT t.id, t.fecha_hora, t.monto_centimos, t.moneda, t.categoria_id,
                  t.comercio_o_destinatario, a.tipo AS cuenta_tipo
           FROM transactions t LEFT JOIN accounts a ON a.id = t.cuenta_id
           WHERE t.creada_en >= ? AND t.tipo = 'gasto' AND t.estado != 'ignorada'
             AND t.moneda IS NOT NULL
           ORDER BY t.monto_centimos DESC""",
        (creadas_desde,),
    ).fetchall()
    atipicos = []
    for i in range(len(nuevas)):
        monto = metricas.en_colones(nuevas[i]["monto_centimos"], nuevas[i]["moneda"], cambio)
        if monto is None or monto <= MINIMO_ATIPICO:
            continue
        referencia = _montos_de_referencia(conn, nuevas[i], cambio)
        if len(referencia) < MUESTRAS_MINIMAS:
            continue
        mediana = statistics.median(referencia)
        if mediana <= 0 or monto <= VECES_ATIPICO * mediana:
            continue
        # Los destinatarios SINPE son terceros: en la notificación no va el nombre.
        descripcion = "un SINPE"
        if nuevas[i]["cuenta_tipo"] != "sinpe" and nuevas[i]["comercio_o_destinatario"]:
            descripcion = nuevas[i]["comercio_o_destinatario"]
        atipicos.append(GastoAtipico(nuevas[i]["id"], descripcion, monto, monto / mediana))
    return atipicos


def avisar_atipicos(conn: sqlite3.Connection, creadas_desde: str) -> int:
    atipicos = gastos_atipicos(conn, creadas_desde)
    if not atipicos:
        return 0
    lineas = []
    for i in range(min(3, len(atipicos))):
        lineas.append(
            f"{formato.formatear_monto(atipicos[i].monto)} en {atipicos[i].descripcion} "
            f"({atipicos[i].veces:.0f}× lo normal)"
        )
    if len(atipicos) > 3:
        lineas.append(f"y {len(atipicos) - 3} más")
    notificar("Finanzas: gasto fuera de lo normal", "\n".join(lineas))
    return len(atipicos)
