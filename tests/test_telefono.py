import json
import shutil
from datetime import datetime, timedelta

import pytest

from conftest import DIR_FIXTURES
from finanzas import alertas, cli, db, telefono
from finanzas.tiempo import ZONA_CR


@pytest.fixture
def carpeta(tmp_path):
    ruta = tmp_path / "finanzas-eventos"
    ruta.mkdir()
    return ruta


def _copiar(carpeta, nombre):
    shutil.copy(DIR_FIXTURES / "sms" / nombre, carpeta / nombre)


def _contar(conn, tabla):
    return conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


@pytest.fixture
def avisos(monkeypatch):
    enviados = []
    monkeypatch.setattr(alertas, "notificar", lambda *args, **kwargs: enviados.append(args))
    return enviados


def test_configurar_crea_stignore_sin_duplicar(conn, carpeta):
    (carpeta / ".stignore").write_text("// mis patrones\n*.tmp", encoding="utf-8")
    assert telefono.configurar(conn, carpeta) == ["procesados", "rechazados"]
    assert telefono.configurar(conn, carpeta) == []
    lineas = (carpeta / ".stignore").read_text(encoding="utf-8").splitlines()
    assert lineas == ["// mis patrones", "*.tmp", "procesados", "rechazados"]
    assert db.leer_ajuste(conn, telefono.AJUSTE_CARPETA) == str(carpeta.resolve())


def test_configurar_carpeta_inexistente(conn, tmp_path):
    with pytest.raises(ValueError):
        telefono.configurar(conn, tmp_path / "no-existe")


def test_sin_configurar_no_hace_nada(conn):
    assert telefono.importar_telefono(conn) is None


def test_importa_y_mueve_a_procesados(conn, carpeta):
    telefono.configurar(conn, carpeta)
    _copiar(carpeta, "almuerzo.json")
    _copiar(carpeta, "pasaje.json")

    resumen = telefono.importar_telefono(conn)

    assert (resumen.nuevos, resumen.duplicados, resumen.rechazados, resumen.errores) == (2, 0, 0, 0)
    assert _contar(conn, "transactions") == 2
    fila = conn.execute(
        "SELECT t.monto_centimos, a.tipo FROM transactions t JOIN accounts a ON a.id = t.cuenta_id "
        "WHERE llave_unica = 'sinpe:2026102215283000000000001'"
    ).fetchone()
    assert (fila["monto_centimos"], fila["tipo"]) == (250000, "sinpe")
    procesados = sorted((carpeta / "procesados").iterdir())
    nombres = []
    for i in range(len(procesados)):
        nombres.append(procesados[i].name)
    assert nombres == ["almuerzo.json", "pasaje.json"]
    assert list(carpeta.glob("*.json")) == []
    # El más reciente por received_at (pasaje: 2026-10-23T13:15:09Z).
    assert db.leer_ajuste(conn, telefono.AJUSTE_ULTIMO_EVENTO) == "2026-10-23T13:15:09Z"
    assert telefono.importar_telefono(conn).nuevos == 0


def test_mismo_evento_otra_vez_es_duplicado(conn, carpeta):
    telefono.configurar(conn, carpeta)
    _copiar(carpeta, "almuerzo.json")
    telefono.importar_telefono(conn)
    _copiar(carpeta, "almuerzo.json")

    resumen = telefono.importar_telefono(conn)

    assert (resumen.nuevos, resumen.duplicados) == (0, 1)
    assert _contar(conn, "transactions") == 1
    assert (carpeta / "procesados" / "almuerzo.json").exists()


def test_rechaza_lo_que_no_cumple_el_esquema(conn, carpeta):
    telefono.configurar(conn, carpeta)
    valido = json.loads((DIR_FIXTURES / "sms" / "almuerzo.json").read_text(encoding="utf-8"))
    malos = {
        "roto.json": "{no es json",
        "lista.json": "[]",
        "version.json": json.dumps(dict(valido, schema_version=2)),
        "fuente.json": json.dumps(dict(valido, source="otra")),
        "sin_zona.json": json.dumps(dict(valido, received_at="2026-10-22T15:28:41")),
        "id_raro.json": json.dumps(dict(valido, event_id="abc")),
    }
    nombres = list(malos)
    for i in range(len(nombres)):
        (carpeta / nombres[i]).write_text(malos[nombres[i]], encoding="utf-8")

    resumen = telefono.importar_telefono(conn)

    assert resumen.rechazados == len(malos)
    assert _contar(conn, "raw_events") == 0
    assert len(list((carpeta / "rechazados").iterdir())) == len(malos)


def test_ignora_ocultos_temporales_y_otros_archivos(conn, carpeta):
    telefono.configurar(conn, carpeta)
    _copiar(carpeta, "almuerzo.json")
    (carpeta / ".syncthing.pasaje.json.tmp").write_text("parcial", encoding="utf-8")
    (carpeta / "~pasaje.json").write_text("parcial", encoding="utf-8")
    (carpeta / "notas.txt").write_text("x", encoding="utf-8")

    resumen = telefono.importar_telefono(conn)

    assert (resumen.nuevos, resumen.rechazados) == (1, 0)
    assert (carpeta / ".syncthing.pasaje.json.tmp").exists()
    assert (carpeta / "notas.txt").exists()


def test_carpeta_borrada_es_error(conn, carpeta):
    telefono.configurar(conn, carpeta)
    shutil.rmtree(carpeta)
    with pytest.raises(FileNotFoundError):
        telefono.importar_telefono(conn)


# --- alertas ---

def test_aviso_de_novedades_una_vez_por_corrida(conn, carpeta, avisos):
    telefono.configurar(conn, carpeta)
    antes = alertas.contar(conn)
    assert alertas.avisar_novedades(conn, antes) is False

    _copiar(carpeta, "almuerzo.json")
    telefono.importar_telefono(conn)
    assert alertas.avisar_novedades(conn, antes) is True
    assert len(avisos) == 1
    assert "1 transacciones nuevas" in avisos[0][1]


def test_aviso_de_telefono_atrasado_una_sola_vez(conn, carpeta, avisos):
    telefono.configurar(conn, carpeta)
    _copiar(carpeta, "almuerzo.json")
    telefono.importar_telefono(conn)
    ultimo = datetime.fromisoformat("2026-10-22T15:28:41-06:00")

    assert alertas.avisar_telefono(conn, ultimo + timedelta(days=2)) is False
    assert alertas.avisar_telefono(conn, ultimo + timedelta(days=3)) is True
    assert alertas.avisar_telefono(conn, ultimo + timedelta(days=5)) is False
    assert len(avisos) == 1

    _copiar(carpeta, "pasaje.json")
    telefono.importar_telefono(conn)
    nuevo = datetime.fromisoformat("2026-10-23T13:15:09+00:00")
    assert alertas.avisar_telefono(conn, nuevo + timedelta(days=1)) is False
    assert alertas.avisar_telefono(conn, nuevo + timedelta(days=4)) is True
    assert len(avisos) == 2


def test_aviso_si_nunca_llegan_eventos(conn, carpeta, avisos):
    telefono.configurar(conn, carpeta)
    situacion = alertas.estado(conn, datetime.now(ZONA_CR) + timedelta(days=4))
    assert situacion.ultimo_evento_telefono is None
    assert situacion.telefono_atrasado is True
    assert alertas.avisar_telefono(conn, datetime.now(ZONA_CR) + timedelta(days=4)) is True


def test_sin_telefono_configurado_no_avisa(conn, avisos):
    assert alertas.avisar_telefono(conn, datetime.now(ZONA_CR)) is False
    assert avisos == []


# --- CLI: aceptación de la Etapa 4 ---

def test_importar_trae_el_sinpe_del_telefono_aunque_gmail_no_este_configurado(tmp_path, carpeta, avisos):
    ruta = tmp_path / "finanzas.db"
    assert cli.main(["--db", str(ruta), "configurar-telefono", str(carpeta)]) == 0
    _copiar(carpeta, "almuerzo.json")

    codigo = cli.main(["--db", str(ruta), "importar"])

    assert codigo == 1  # Gmail sin configurar en esta prueba
    conn = db.conectar(ruta)
    try:
        assert _contar(conn, "transactions") == 1
    finally:
        conn.close()
    assert (carpeta / "procesados" / "almuerzo.json").exists()
    titulos = []
    for i in range(len(avisos)):
        titulos.append(avisos[i][0])
    assert "Finanzas: hay cosas por revisar" in titulos


def test_importar_hace_backup_diario(tmp_path, carpeta, avisos, monkeypatch):
    from finanzas import resumen
    monkeypatch.setattr(resumen, "notificar", lambda *args, **kwargs: None)
    ruta = tmp_path / "finanzas.db"
    cli.main(["--db", str(ruta), "configurar-telefono", str(carpeta)])
    cli.main(["--db", str(ruta), "importar"])
    respaldos = list((tmp_path / "backups").glob("finanzas-*.db"))
    assert len(respaldos) == 1
