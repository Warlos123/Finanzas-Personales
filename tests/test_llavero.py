import subprocess

import pytest

from finanzas import llavero, notificar


class _RegistroRun:
    def __init__(self, returncode=0, stdout=""):
        self.llamadas = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, comando, **kwargs):
        self.llamadas.append((comando, kwargs))
        return subprocess.CompletedProcess(comando, self.returncode, self.stdout, "")


def test_guardar_pasa_la_contrasena_por_stdin(monkeypatch):
    registro = _RegistroRun()
    monkeypatch.setattr(llavero.subprocess, "run", registro)

    llavero.guardar_contrasena("yo@gmail.com", "abcdefghijklmnop")

    comando, kwargs = registro.llamadas[0]
    assert comando[:2] == ["secret-tool", "store"]
    assert "abcdefghijklmnop" not in comando
    assert kwargs["input"] == "abcdefghijklmnop"


def test_leer_devuelve_contrasena_o_none(monkeypatch):
    monkeypatch.setattr(llavero.subprocess, "run", _RegistroRun(stdout="abcdefghijklmnop\n"))
    assert llavero.leer_contrasena("yo@gmail.com") == "abcdefghijklmnop"

    monkeypatch.setattr(llavero.subprocess, "run", _RegistroRun(returncode=1))
    assert llavero.leer_contrasena("yo@gmail.com") is None


def test_sin_secret_tool_es_error_claro(monkeypatch):
    def no_existe(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(llavero.subprocess, "run", no_existe)
    with pytest.raises(llavero.ErrorLlavero):
        llavero.leer_contrasena("yo@gmail.com")


def test_notificar_sin_notify_send_no_falla(monkeypatch):
    def no_existe(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(notificar.subprocess, "run", no_existe)
    notificar.notificar("titulo", "cuerpo")
