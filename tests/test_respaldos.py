import sqlite3
from datetime import date, timedelta

from conftest import leer_fixture
from finanzas import ingesta, respaldos


def test_backup_diario_una_vez_por_dia_y_es_una_base_valida(conn, tmp_path):
    ingesta.importar_evento(conn, "gmail_bcr", leer_fixture("bcr/una_fila.html"), "2026-10-26T08:45:00-06:00")
    ruta_db = tmp_path / "prueba.db"

    creado = respaldos.diario(conn, ruta_db, date(2026, 10, 27))
    assert creado == tmp_path / "backups" / "finanzas-2026-10-27.db"
    assert respaldos.diario(conn, ruta_db, date(2026, 10, 27)) is None

    copia = sqlite3.connect(creado)
    try:
        assert copia.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    finally:
        copia.close()
    assert list((tmp_path / "backups").glob("*.tmp")) == []


def test_conserva_solo_los_ultimos_14(conn, tmp_path):
    ruta_db = tmp_path / "prueba.db"
    inicio = date(2026, 10, 1)
    for i in range(20):
        respaldos.diario(conn, ruta_db, inicio + timedelta(days=i))

    archivos = sorted((tmp_path / "backups").glob("finanzas-*.db"))
    assert len(archivos) == 14
    assert archivos[0].name == "finanzas-2026-10-07.db"
    assert archivos[-1].name == "finanzas-2026-10-20.db"
