"""Reconciliación: compara un estado de cuenta del BCR con las transacciones de la app.

- Compras con tarjeta: por autorización (el Documento del estado es la autorización del correo
  sin ceros a la izquierda) y últimos 4 de la tarjeta.
- Lo demás (SINPE, transferencias, intereses, comisiones): mismo monto y moneda, misma dirección
  (débito con gasto/transferencia/reembolsable, crédito con ingreso/transferencia/reembolsable)
  y a lo sumo DIAS_MARGEN días de diferencia; gana la más cercana.
- Lo agregado desde un estado lleva la llave `estado:<fecha>:<documento>:<céntimos>`: subir el
  mismo estado otra vez no duplica nada y esas filas cuentan como coincidencias.
- Los movimientos internos (CDP, paso a la tarjeta virtual) se listan aparte y no se proponen.
Ninguna función hace commit.
"""

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from finanzas import estado_cuenta, reglas
from finanzas.estado_cuenta import EstadoCuenta, Movimiento
from finanzas.movimientos import TIPOS
from finanzas.tiempo import ahora_iso

TIPOS_DEBITO = ("gasto", "transferencia", "reembolsable")
TIPOS_CREDITO = ("ingreso", "transferencia", "reembolsable")
DIAS_MARGEN = 3
CUENTA_AHORROS = "Cuenta de ahorros BCR"

_SQL_CANDIDATAS = """
SELECT t.*, a.tipo AS cuenta_tipo, a.ultimos4 AS cuenta_ultimos4, a.nombre AS cuenta_nombre
FROM transactions t LEFT JOIN accounts a ON a.id = t.cuenta_id
WHERE t.fecha_hora >= ? AND t.fecha_hora < ?
ORDER BY t.fecha_hora, t.id
"""


@dataclass
class Linea:
    indice: int
    movimiento: Movimiento
    transaccion: sqlite3.Row | None = None

    @property
    def tipo_sugerido(self) -> str:
        if self.movimiento.credito:
            return "ingreso"
        return "gasto"


@dataclass
class Reconciliacion:
    estado: EstadoCuenta
    coinciden: list = field(default_factory=list)
    faltan: list = field(default_factory=list)  # en el banco, no en la app
    montos_distintos: list = field(default_factory=list)  # misma autorización, otro monto
    internos: list = field(default_factory=list)
    solo_en_app: list = field(default_factory=list)  # filas de transactions


def guardar(conn: sqlite3.Connection, texto: str) -> int:
    """Valida el texto (lanza ValueError si no se puede leer o no cuadra) y lo guarda una sola vez."""
    estado = estado_cuenta.leer(texto)
    huella = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    fila = conn.execute("SELECT id FROM bank_statements WHERE hash = ?", (huella,)).fetchone()
    if fila is not None:
        return fila["id"]
    cursor = conn.execute(
        "INSERT INTO bank_statements (hash, texto, desde, hasta, creado_en) VALUES (?, ?, ?, ?, ?)",
        (huella, texto, estado.desde, estado.hasta, ahora_iso()),
    )
    return cursor.lastrowid


def listar(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT id, desde, hasta, creado_en FROM bank_statements ORDER BY desde DESC, id DESC"
    ).fetchall()


def obtener(conn: sqlite3.Connection, estado_id: int) -> EstadoCuenta | None:
    fila = conn.execute("SELECT texto FROM bank_statements WHERE id = ?", (estado_id,)).fetchone()
    if fila is None:
        return None
    return estado_cuenta.leer(fila["texto"])


def _dia(iso: str, delta: int) -> str:
    return (date.fromisoformat(iso[:10]) + timedelta(days=delta)).isoformat()


def _dias_entre(a: str, b: str) -> int:
    return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)


def _autorizacion(llave: str | None) -> int | None:
    """'bcr:00656607:608913462673' -> 656607."""
    if llave is None or not llave.startswith("bcr:"):
        return None
    partes = llave.split(":")
    if len(partes) < 3 or not partes[1].isdigit():
        return None
    return int(partes[1])


def _mas_cercana(candidatas: list, usadas: set, movimiento: Movimiento, moneda: str):
    tipos = TIPOS_DEBITO
    if movimiento.credito:
        tipos = TIPOS_CREDITO
    mejor = None
    mejor_distancia = None
    for i in range(len(candidatas)):
        t = candidatas[i]
        if t["id"] in usadas or _autorizacion(t["llave_unica"]) is not None:
            continue
        if t["monto_centimos"] != movimiento.monto_centimos or t["moneda"] != moneda:
            continue
        if t["tipo"] not in tipos:
            continue
        distancia = _dias_entre(t["fecha_hora"], movimiento.fecha)
        if distancia > DIAS_MARGEN:
            continue
        if mejor is None or distancia < mejor_distancia:
            mejor = t
            mejor_distancia = distancia
    return mejor


def reconciliar(conn: sqlite3.Connection, estado: EstadoCuenta) -> Reconciliacion:
    resultado = Reconciliacion(estado=estado)
    # Las compras pueden tener fecha de movimiento unos días antes del período.
    candidatas = conn.execute(_SQL_CANDIDATAS, (_dia(estado.desde, -10), _dia(estado.hasta, 8))).fetchall()
    por_llave = {}
    por_autorizacion = {}
    for i in range(len(candidatas)):
        t = candidatas[i]
        if t["llave_unica"] is not None:
            por_llave[t["llave_unica"]] = t
        autorizacion = _autorizacion(t["llave_unica"])
        if autorizacion is not None:
            por_autorizacion.setdefault((t["cuenta_ultimos4"], autorizacion), []).append(t)

    usadas = set()
    pendientes = []
    tarjetas = set()
    # Primera pasada: coincidencias exactas (llave del estado o autorización).
    for i in range(len(estado.movimientos)):
        linea = Linea(indice=i, movimiento=estado.movimientos[i])
        movimiento = linea.movimiento
        if movimiento.tarjeta is not None:
            tarjetas.add(movimiento.tarjeta)
        if movimiento.clase == "interno":
            resultado.internos.append(linea)
            continue
        t = por_llave.get(movimiento.llave)
        if t is None and movimiento.clase == "compra":
            mismas = por_autorizacion.get((movimiento.tarjeta, int(movimiento.documento)), [])
            for j in range(len(mismas)):
                if mismas[j]["id"] not in usadas:
                    t = mismas[j]
                    break
        if t is None:
            pendientes.append(linea)
            continue
        usadas.add(t["id"])
        linea.transaccion = t
        if t["moneda"] == estado.moneda and t["monto_centimos"] != movimiento.monto_centimos:
            resultado.montos_distintos.append(linea)
        else:
            resultado.coinciden.append(linea)

    # Segunda pasada: monto y fecha (las compras solo se emparejan por autorización).
    for i in range(len(pendientes)):
        linea = pendientes[i]
        t = None
        if linea.movimiento.clase != "compra":
            t = _mas_cercana(candidatas, usadas, linea.movimiento, estado.moneda)
        if t is None:
            resultado.faltan.append(linea)
            continue
        usadas.add(t["id"])
        linea.transaccion = t
        resultado.coinciden.append(linea)

    # En la app pero no en el banco: dentro del período, de las cuentas que cubre el estado.
    for i in range(len(candidatas)):
        t = candidatas[i]
        if t["id"] in usadas or t["estado"] == "ignorada":
            continue
        if t["fecha_hora"][:10] < estado.desde or t["fecha_hora"][:10] > estado.hasta:
            continue
        de_tarjeta = t["cuenta_tipo"] == "tarjeta" and t["cuenta_ultimos4"] in tarjetas
        del_estado = t["llave_unica"] is not None and t["llave_unica"].startswith("estado:")
        if de_tarjeta or t["cuenta_tipo"] == "sinpe" or del_estado:
            resultado.solo_en_app.append(t)
    return resultado


def _cuenta_id(conn: sqlite3.Connection, movimiento: Movimiento, moneda: str) -> int:
    """Tarjeta por últimos 4, la cuenta SINPE, o la cuenta de ahorros; las crea si faltan."""
    if movimiento.clase == "compra":
        fila = conn.execute(
            "SELECT id FROM accounts WHERE tipo = 'tarjeta' AND ultimos4 = ? ORDER BY id LIMIT 1",
            (movimiento.tarjeta,),
        ).fetchone()
        nueva = (f"Tarjeta BCR ****{movimiento.tarjeta}", "tarjeta", movimiento.tarjeta)
    elif movimiento.clase == "sinpe":
        fila = conn.execute("SELECT id FROM accounts WHERE tipo = 'sinpe' ORDER BY id LIMIT 1").fetchone()
        nueva = ("SINPE Móvil", "sinpe", None)
    else:
        fila = conn.execute(
            "SELECT id FROM accounts WHERE nombre = ? ORDER BY id LIMIT 1", (CUENTA_AHORROS,)
        ).fetchone()
        nueva = (CUENTA_AHORROS, "otra", None)
    if fila is not None:
        return fila["id"]
    cursor = conn.execute(
        "INSERT INTO accounts (nombre, tipo, ultimos4, moneda) VALUES (?, ?, ?, ?)",
        (nueva[0], nueva[1], nueva[2], moneda),
    )
    return cursor.lastrowid


def agregar(conn: sqlite3.Connection, estado: EstadoCuenta, elecciones: list[tuple[int, str]]) -> tuple[int, int]:
    """Crea transacciones para los movimientos elegidos: (índice, tipo) con tipo en TIPOS o
    'ignorar' (queda guardada como ignorada, para que no vuelva a aparecer como faltante).
    Devuelve (agregadas, ignoradas). Las que ya existen o son internas se saltan."""
    agregadas = 0
    ignoradas = 0
    for i in range(len(elecciones)):
        indice, tipo = elecciones[i]
        if indice < 0 or indice >= len(estado.movimientos):
            raise ValueError("Movimiento inexistente")
        if tipo != "ignorar" and tipo not in TIPOS:
            raise ValueError("Tipo inválido")
        movimiento = estado.movimientos[indice]
        if movimiento.clase == "interno":
            continue
        existe = conn.execute(
            "SELECT 1 FROM transactions WHERE llave_unica = ?", (movimiento.llave,)
        ).fetchone()
        if existe is not None:
            continue
        estado_tx = "confirmada"
        if tipo == "ignorar":
            estado_tx = "ignorada"
            tipo = Linea(indice=indice, movimiento=movimiento).tipo_sugerido
        comercio = movimiento.texto
        descripcion = None
        if movimiento.clase == "sinpe":
            comercio = None
            descripcion = movimiento.texto
        elif movimiento.clase == "otro":
            descripcion = movimiento.tipo
        cursor = conn.execute(
            """INSERT INTO transactions (fecha_hora, monto_centimos, moneda, tipo, cuenta_id,
                   comercio_o_destinatario, descripcion, estado, llave_unica, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                movimiento.fecha + "T00:00:00-06:00", movimiento.monto_centimos, estado.moneda, tipo,
                _cuenta_id(conn, movimiento, estado.moneda), comercio, descripcion, estado_tx,
                movimiento.llave, ahora_iso(),
            ),
        )
        if estado_tx == "ignorada":
            ignoradas += 1
        else:
            agregadas += 1
            reglas.aplicar_reglas(conn, [cursor.lastrowid])
    return agregadas, ignoradas
