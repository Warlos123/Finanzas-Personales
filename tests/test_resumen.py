from datetime import date

import pytest

from finanzas import catalogos, formato, metricas, movimientos, resumen


def _mov(conn, fecha, monto, tipo="gasto", nombre="SODA", categoria=None):
    categoria_id = None
    if categoria is not None:
        categoria_id = conn.execute("SELECT id FROM categories WHERE nombre = ?", (categoria,)).fetchone()["id"]
    datos = movimientos.DatosTransaccion(
        fecha_hora=formato.fecha_desde_formulario(fecha), monto_centimos=monto, moneda="CRC", tipo=tipo,
        cuenta_id=None, categoria_id=categoria_id, comercio_o_destinatario=nombre, notas=None,
    )
    return movimientos.crear_manual(conn, datos)


@pytest.fixture
def avisos(monkeypatch):
    enviados = []
    monkeypatch.setattr(resumen, "notificar", lambda *args, **kwargs: enviados.append(args))
    return enviados


def test_gastos_mas_grandes_del_mes(conn):
    _mov(conn, "2026-10-02", 1000000, nombre="A")
    _mov(conn, "2026-10-03", 5000000, nombre="B")
    _mov(conn, "2026-10-04", 3000000, nombre="C")
    _mov(conn, "2026-10-05", 9000000, tipo="transferencia", nombre="PAGO")
    _mov(conn, "2026-09-30", 9900000, nombre="OTRO MES")

    grandes = metricas.gastos_mas_grandes(conn, "2026-10", 2)

    nombres = []
    for i in range(len(grandes)):
        nombres.append(grandes[i].nombre)
    assert nombres == ["B", "C"]


def test_resumen_del_mes_anterior_una_sola_vez(conn, tmp_path, avisos):
    _mov(conn, "2026-10-01", 50000000, tipo="ingreso", nombre="Salario")
    _mov(conn, "2026-10-05", 1200000, nombre="SUPER", categoria="Supermercado")
    supermercado = conn.execute("SELECT id FROM categories WHERE nombre = 'Supermercado'").fetchone()["id"]
    catalogos.guardar_presupuesto(conn, supermercado, 1000000)
    ruta_db = tmp_path / "finanzas.db"

    archivo = resumen.mensual(conn, ruta_db, date(2026, 11, 1))

    assert archivo == tmp_path / "resumenes" / "2026-10.md"
    texto = archivo.read_text(encoding="utf-8")
    assert texto.startswith("# Resumen de octubre 2026")
    assert "| Gasto | ₡12,000.00 |" in texto
    assert "Supermercado: ₡12,000.00 de ₡10,000.00 (120%) — excedido" in texto
    assert "SUPER" in texto
    assert len(avisos) == 1
    assert resumen.mensual(conn, ruta_db, date(2026, 11, 2)) is None
    assert len(avisos) == 1


def test_sin_datos_no_genera(conn, tmp_path, avisos):
    assert resumen.mensual(conn, tmp_path / "finanzas.db", date(2026, 11, 1)) is None
    assert avisos == []
