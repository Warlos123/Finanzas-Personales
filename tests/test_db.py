from finanzas import db


def test_migraciones_crean_todas_las_tablas(conn):
    filas = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    nombres = set()
    for i in range(len(filas)):
        nombres.add(filas[i]["name"])
    esperadas = {
        "raw_events", "transactions", "accounts", "categories", "rules",
        "recurring_incomes", "budgets", "import_runs", "settings",
    }
    assert esperadas <= nombres


def test_modo_wal_y_llaves_foraneas(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrar_dos_veces_no_falla(tmp_path):
    ruta = tmp_path / "doble.db"
    primera = db.conectar(ruta)
    version = primera.execute("PRAGMA user_version").fetchone()[0]
    primera.close()

    segunda = db.conectar(ruta)
    assert db.migrar(segunda) == version
    assert version >= 1
    segunda.close()


def test_ajustes_guardar_leer_y_borrar(conn):
    assert db.leer_ajuste(conn, "x") is None
    assert db.leer_ajuste(conn, "x", "defecto") == "defecto"
    db.guardar_ajuste(conn, "x", 5)
    db.guardar_ajuste(conn, "x", 7)
    assert db.leer_ajuste(conn, "x") == "7"
    db.guardar_ajuste(conn, "x", None)
    assert db.leer_ajuste(conn, "x") is None


def test_ruta_por_defecto_respeta_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert db.ruta_por_defecto() == tmp_path / "finanzas" / "finanzas.db"
