"""Importa los eventos JSON que el teléfono deja en la carpeta de Syncthing.

- Lee los `*.json` de la raíz de la carpeta (ignora ocultos y temporales de Syncthing).
- Cada archivo válido se registra como evento crudo `sms_4066` y se mueve a `procesados/`.
- Los que no cumplen el esquema se mueven a `rechazados/` sin importarse.
- En la PC, Syncthing ignora `procesados` y `rechazados` (.stignore): al mover un archivo,
  el teléfono lo ve como borrado y limpia su carpeta; la PC conserva la copia.
Los logs solo llevan conteos: nunca el cuerpo del SMS ni nombres.
"""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finanzas import db, ingesta
from finanzas.tiempo import ahora_iso

log = logging.getLogger(__name__)

FUENTE = "sms_4066"
AJUSTE_CARPETA = "telefono_carpeta"
AJUSTE_CONFIGURADO_EN = "telefono_configurado_en"
AJUSTE_ULTIMO_EVENTO = "telefono_ultimo_evento"
PROCESADOS = "procesados"
RECHAZADOS = "rechazados"
# Un evento real pesa menos de 1 KB; algo mucho más grande no es del teléfono.
TAMANO_MAXIMO = 64 * 1024


@dataclass
class ResumenTelefono:
    nuevos: int = 0
    duplicados: int = 0
    rechazados: int = 0
    errores: int = 0


def _asegurar_stignore(carpeta: Path) -> list[str]:
    """Agrega `procesados` y `rechazados` al .stignore de Syncthing. Devuelve los que agregó."""
    archivo = carpeta / ".stignore"
    existentes = []
    if archivo.exists():
        existentes = archivo.read_text(encoding="utf-8").splitlines()
    limpias = []
    for i in range(len(existentes)):
        limpias.append(existentes[i].strip())
    agregados = []
    patrones = (PROCESADOS, RECHAZADOS)
    for i in range(len(patrones)):
        if patrones[i] not in limpias:
            agregados.append(patrones[i])
    if agregados:
        texto = ""
        if existentes and existentes[-1] != "":
            texto = "\n"
        texto = texto + "\n".join(agregados) + "\n"
        with archivo.open("a", encoding="utf-8") as salida:
            salida.write(texto)
    return agregados


def configurar(conn: sqlite3.Connection, ruta: Path) -> list[str]:
    """Guarda la carpeta y prepara el .stignore. Devuelve los patrones agregados."""
    carpeta = Path(ruta).expanduser().resolve()
    if not carpeta.is_dir():
        raise ValueError(f"No existe la carpeta {carpeta}")
    agregados = _asegurar_stignore(carpeta)
    with conn:
        db.guardar_ajuste(conn, AJUSTE_CARPETA, str(carpeta))
        db.guardar_ajuste(conn, AJUSTE_CONFIGURADO_EN, ahora_iso())
    return agregados


def leer_evento(archivo: Path) -> dict | None:
    """El evento si cumple el esquema (schema_version 1); si no, None."""
    if archivo.stat().st_size > TAMANO_MAXIMO:
        return None
    try:
        evento = json.loads(archivo.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(evento, dict):
        return None
    if evento.get("schema_version") != 1 or evento.get("source") != FUENTE:
        return None
    campos = ("event_id", "received_at", "body")
    for i in range(len(campos)):
        valor = evento.get(campos[i])
        if not isinstance(valor, str) or valor.strip() == "":
            return None
    if not evento["event_id"].isdigit():
        return None
    try:
        recibido = datetime.fromisoformat(evento["received_at"])
    except ValueError:
        return None
    if recibido.tzinfo is None:
        return None
    return evento


def _archivos_pendientes(carpeta: Path) -> list[Path]:
    """`*.json` de la raíz, sin ocultos ni temporales de Syncthing (`.syncthing.*`, `~…`)."""
    candidatos = sorted(carpeta.iterdir())
    archivos = []
    for i in range(len(candidatos)):
        nombre = candidatos[i].name
        if nombre.startswith(".") or nombre.startswith("~"):
            continue
        if candidatos[i].suffix != ".json" or not candidatos[i].is_file():
            continue
        archivos.append(candidatos[i])
    return archivos


def _mover(archivo: Path, subcarpeta: str) -> None:
    destino = archivo.parent / subcarpeta
    destino.mkdir(exist_ok=True)
    os.replace(archivo, destino / archivo.name)


def _es_mas_reciente(nuevo: str, actual: str | None) -> bool:
    if actual is None:
        return True
    return datetime.fromisoformat(nuevo) > datetime.fromisoformat(actual)


def importar_telefono(conn: sqlite3.Connection) -> ResumenTelefono | None:
    """Importa lo que haya en la carpeta. None si el teléfono no está configurado."""
    ruta = db.leer_ajuste(conn, AJUSTE_CARPETA)
    if ruta is None:
        return None
    carpeta = Path(ruta)
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta del teléfono {carpeta}")

    resumen = ResumenTelefono()
    archivos = _archivos_pendientes(carpeta)
    if not archivos:
        return resumen
    inicio = ahora_iso()
    ultimo = db.leer_ajuste(conn, AJUSTE_ULTIMO_EVENTO)
    for i in range(len(archivos)):
        evento = leer_evento(archivos[i])
        if evento is None:
            _mover(archivos[i], RECHAZADOS)
            resumen.rechazados += 1
            continue
        _, es_nuevo, proceso = ingesta.importar_evento(conn, FUENTE, evento["body"], evento["received_at"])
        if es_nuevo:
            resumen.nuevos += 1
        else:
            resumen.duplicados += 1
        if proceso.error:
            resumen.errores += 1
        if _es_mas_reciente(evento["received_at"], ultimo):
            ultimo = evento["received_at"]
        _mover(archivos[i], PROCESADOS)

    with conn:
        db.guardar_ajuste(conn, AJUSTE_ULTIMO_EVENTO, ultimo)
        conn.execute(
            "INSERT INTO import_runs (fuente, inicio, fin, nuevos, duplicados, errores) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (FUENTE, inicio, ahora_iso(), resumen.nuevos, resumen.duplicados,
             resumen.errores + resumen.rechazados),
        )
    return resumen
