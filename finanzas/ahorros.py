"""Ahorros e inversiones: CDP y S&P 500. Por ahora los valores se ingresan a mano.

- El valor actual vacío se toma igual a lo invertido (un CDP que paga cupones no cambia de valor).
- Los totales van en colones: los dólares se convierten con el tipo de cambio del día; si no
  hay, se muestran aparte.
Ninguna función hace commit.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from finanzas import metricas
from finanzas.movimientos import MONEDAS
from finanzas.tiempo import ahora_iso

TIPOS = ("cdp", "sp500")
NOMBRES_TIPO = {"cdp": "CDP", "sp500": "S&P 500"}


@dataclass
class DatosAhorro:
    tipo: str
    nombre: str
    moneda: str
    invertido_centimos: int
    valor_actual_centimos: int | None  # None = igual a lo invertido
    tasa_anual: str | None
    inicio: str | None
    vence: str | None
    notas: str | None


@dataclass
class Ahorro:
    fila: sqlite3.Row
    dias_para_vencer: int | None

    @property
    def ganancia(self) -> int:
        return self.fila["valor_actual_centimos"] - self.fila["invertido_centimos"]

    @property
    def rendimiento(self) -> float | None:
        if self.fila["invertido_centimos"] <= 0:
            return None
        return self.ganancia / self.fila["invertido_centimos"]


@dataclass
class Resumen:
    total: int = 0  # céntimos de colón
    invertido: int = 0
    por_tipo: dict = field(default_factory=dict)  # tipo -> céntimos de colón
    sin_convertir: int = 0  # céntimos de dólar sin tipo de cambio

    @property
    def ganancia(self) -> int:
        return self.total - self.invertido

    @property
    def rendimiento(self) -> float | None:
        if self.invertido <= 0:
            return None
        return self.ganancia / self.invertido


def _fecha_opcional(texto: str | None) -> str | None:
    if texto is None:
        return None
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        raise ValueError("Fecha inválida") from None


def _validar(datos: DatosAhorro) -> DatosAhorro:
    if datos.tipo not in TIPOS:
        raise ValueError("Tipo de ahorro inválido")
    datos.nombre = datos.nombre.strip()
    if datos.nombre == "":
        raise ValueError("El nombre no puede estar vacío")
    if datos.moneda not in MONEDAS:
        raise ValueError("Moneda inválida")
    if datos.invertido_centimos < 0:
        raise ValueError("El monto no puede ser negativo")
    if datos.valor_actual_centimos is None:
        datos.valor_actual_centimos = datos.invertido_centimos
    if datos.valor_actual_centimos < 0:
        raise ValueError("El valor actual no puede ser negativo")
    if datos.tasa_anual is not None:
        try:
            tasa = Decimal(datos.tasa_anual.replace("%", "").strip())
        except InvalidOperation:
            raise ValueError("Tasa inválida (ej. 5.25)") from None
        if not tasa.is_finite() or tasa < 0 or tasa >= 100:
            raise ValueError("Tasa inválida (ej. 5.25)")
        datos.tasa_anual = str(tasa)
    datos.inicio = _fecha_opcional(datos.inicio)
    datos.vence = _fecha_opcional(datos.vence)
    return datos


def guardar(conn: sqlite3.Connection, ahorro_id: int | None, datos: DatosAhorro) -> int:
    datos = _validar(datos)
    valores = (
        datos.tipo, datos.nombre, datos.moneda, datos.invertido_centimos, datos.valor_actual_centimos,
        datos.tasa_anual, datos.inicio, datos.vence, datos.notas, ahora_iso(),
    )
    if ahorro_id is None:
        cursor = conn.execute(
            """INSERT INTO savings (tipo, nombre, moneda, invertido_centimos, valor_actual_centimos,
                   tasa_anual, inicio, vence, notas, actualizado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            valores,
        )
        return cursor.lastrowid
    conn.execute(
        """UPDATE savings SET tipo = ?, nombre = ?, moneda = ?, invertido_centimos = ?,
               valor_actual_centimos = ?, tasa_anual = ?, inicio = ?, vence = ?, notas = ?,
               actualizado_en = ?
           WHERE id = ?""",
        valores + (ahorro_id,),
    )
    return ahorro_id


def obtener(conn: sqlite3.Connection, ahorro_id: int):
    return conn.execute("SELECT * FROM savings WHERE id = ?", (ahorro_id,)).fetchone()


def borrar(conn: sqlite3.Connection, ahorro_id: int) -> None:
    conn.execute("DELETE FROM savings WHERE id = ?", (ahorro_id,))


def listar(conn: sqlite3.Connection, hoy: date) -> list[Ahorro]:
    """Por tipo; los CDP por vencimiento (los sin fecha al final)."""
    filas = conn.execute(
        "SELECT * FROM savings ORDER BY tipo, vence IS NULL, vence, nombre"
    ).fetchall()
    lista = []
    for i in range(len(filas)):
        dias = None
        if filas[i]["vence"]:
            dias = (date.fromisoformat(filas[i]["vence"]) - hoy).days
        lista.append(Ahorro(fila=filas[i], dias_para_vencer=dias))
    return lista


def resumir(conn: sqlite3.Connection, lista: list[Ahorro]) -> Resumen:
    cambio = metricas.tipo_cambio(conn)
    resumen = Resumen()
    for i in range(len(TIPOS)):
        resumen.por_tipo[TIPOS[i]] = 0
    for i in range(len(lista)):
        fila = lista[i].fila
        valor = metricas.en_colones(fila["valor_actual_centimos"], fila["moneda"], cambio)
        invertido = metricas.en_colones(fila["invertido_centimos"], fila["moneda"], cambio)
        if valor is None:
            resumen.sin_convertir += fila["valor_actual_centimos"]
            continue
        resumen.total += valor
        resumen.invertido += invertido
        resumen.por_tipo[fila["tipo"]] = resumen.por_tipo.get(fila["tipo"], 0) + valor
    return resumen
