"""Estado de sincronización y alertas de escritorio.

- Novedades: un solo aviso por corrida si entraron transacciones a la bandeja o eventos que
  no se pudieron interpretar.
- Teléfono: aviso si pasan DIAS_SIN_TELEFONO sin eventos nuevos. Se mide por el último evento
  importado (o, si nunca llegó uno, por la fecha en que se configuró la carpeta). Se avisa una
  sola vez por cada "último evento"; un evento nuevo rearma el aviso.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from finanzas import db, movimientos, telefono
from finanzas.notificar import notificar

DIAS_SIN_TELEFONO = 3
AJUSTE_AVISO_TELEFONO = "aviso_telefono_para"


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
