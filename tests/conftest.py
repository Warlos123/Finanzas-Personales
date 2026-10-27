import json
from pathlib import Path

import urllib.request

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


@pytest.fixture(autouse=True)
def sin_internet(monkeypatch):
    """Ninguna prueba sale a internet (p. ej. el tipo de cambio de Hacienda en `importar`)."""
    def sin_red(*args, **kwargs):
        raise OSError("sin red en las pruebas")

    monkeypatch.setattr(urllib.request, "urlopen", sin_red)
