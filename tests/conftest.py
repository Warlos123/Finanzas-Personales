import json
from pathlib import Path

import pytest

from finanzas import db

DIR_FIXTURES = Path(__file__).parent / "fixtures"


def leer_fixture(ruta_relativa: str) -> str:
    return (DIR_FIXTURES / ruta_relativa).read_text(encoding="utf-8")


def leer_evento_sms(nombre: str) -> dict:
    """Evento JSON tal como lo escribe la app Android en la carpeta Syncthing."""
    return json.loads(leer_fixture("sms/" + nombre))


@pytest.fixture
def conn(tmp_path):
    conexion = db.conectar(tmp_path / "prueba.db")
    yield conexion
    conexion.close()
