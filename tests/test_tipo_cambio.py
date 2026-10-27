import io
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from conftest import leer_fixture
from finanzas import cli, db, metricas, tipo_cambio
from finanzas.tiempo import ZONA_CR

AHORA = datetime(2026, 10, 27, 6, 5, tzinfo=ZONA_CR)


def test_lee_la_venta_con_dos_decimales():
    assert tipo_cambio.leer_venta(leer_fixture("tipo_cambio/hacienda.json")) == Decimal("508.12")


def test_rechaza_respuestas_raras():
    raras = ["no es json", "[]", '{"venta": {}}', '{"venta": {"valor": null}}',
             '{"venta": {"valor": "abc"}}', '{"venta": {"valor": 0}}', '{"venta": {"valor": -1}}']
    for i in range(len(raras)):
        with pytest.raises(ValueError):
            tipo_cambio.leer_venta(raras[i])


def test_consulta_hacienda_con_tiempo_limite(monkeypatch):
    pedidos = []

    def abrir(pedido, timeout):
        pedidos.append((pedido.full_url, timeout))
        return io.BytesIO(leer_fixture("tipo_cambio/hacienda.json").encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", abrir)
    assert tipo_cambio.consultar() == Decimal("508.12")
    assert pedidos == [("https://api.hacienda.go.cr/indicadores/tc/dolar", 15)]


def test_actualiza_una_vez_por_dia(conn, monkeypatch):
    valores = [Decimal("508.12"), Decimal("509.00")]
    llamadas = []

    def consultar():
        llamadas.append(1)
        return valores[len(llamadas) - 1]

    monkeypatch.setattr(tipo_cambio, "consultar", consultar)
    assert tipo_cambio.actualizar(conn, AHORA) == Decimal("508.12")
    assert metricas.tipo_cambio(conn) == Decimal("508.12")
    assert db.leer_ajuste(conn, tipo_cambio.AJUSTE_ACTUALIZADO) == "2026-10-27T06:05:00-06:00"

    assert tipo_cambio.actualizar(conn, AHORA + timedelta(hours=12)) is None
    assert len(llamadas) == 1

    assert tipo_cambio.actualizar(conn, AHORA + timedelta(days=1)) == Decimal("509.00")
    assert metricas.tipo_cambio(conn) == Decimal("509.00")


def test_si_falla_no_toca_el_valor_anterior(conn):
    with conn:
        db.guardar_ajuste(conn, metricas.AJUSTE_TIPO_CAMBIO, "505.50")
    with pytest.raises(OSError):
        tipo_cambio.actualizar(conn, AHORA)  # conftest bloquea la red
    assert metricas.tipo_cambio(conn) == Decimal("505.50")
    assert db.leer_ajuste(conn, tipo_cambio.AJUSTE_ACTUALIZADO) is None


def test_importar_actualiza_el_tipo_de_cambio(tmp_path, monkeypatch):
    monkeypatch.setattr(tipo_cambio, "consultar", lambda: Decimal("508.12"))
    ruta = tmp_path / "f.db"
    cli.main(["--db", str(ruta), "importar"])  # sin Gmail ni teléfono: las tareas igual corren

    conn = db.conectar(ruta)
    try:
        assert metricas.tipo_cambio(conn) == Decimal("508.12")
    finally:
        conn.close()
