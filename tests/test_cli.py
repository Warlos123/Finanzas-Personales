from conftest import leer_fixture
from finanzas import cli, db, gmail, ingesta


def test_reprocesar_por_cli(tmp_path, capsys):
    ruta = tmp_path / "finanzas.db"
    conn = db.conectar(ruta)
    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/una_fila.html"), "2026-10-26T08:45:00-06:00")
    conn.close()

    assert cli.main(["--db", str(ruta), "reprocesar"]) == 0
    assert cli.main(["--db", str(ruta), "reprocesar", "--fuente", "gmail_bcr"]) == 0
    salida = capsys.readouterr().out
    assert "0 transacciones nuevas, 1 existentes" in salida


def test_configurar_quita_espacios_de_la_contrasena(tmp_path, monkeypatch):
    recibidas = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda texto: "abcd efgh ijkl mnop")
    monkeypatch.setattr(gmail, "configurar", lambda conn, u, c: recibidas.append((u, c)))

    codigo = cli.main(["--db", str(tmp_path / "f.db"), "configurar-gmail", "yo@example.com"])

    assert codigo == 0
    assert recibidas == [("yo@example.com", "abcdefghijklmnop")]


def test_importar_sin_configurar_devuelve_1(tmp_path):
    assert cli.main(["--db", str(tmp_path / "f.db"), "importar"]) == 1
