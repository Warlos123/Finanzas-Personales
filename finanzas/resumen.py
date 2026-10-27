"""Resumen mensual automático.

El primer `importar` de cada mes escribe `resumenes/AAAA-MM.md` (junto a la base) con el mes
anterior y avisa con los números clave. Si el archivo ya existe, no hace nada.
"""

import sqlite3
from datetime import date
from pathlib import Path

from finanzas import formato, metricas, suscripciones
from finanzas.notificar import notificar


def carpeta_resumenes(ruta_db) -> Path:
    return Path(ruta_db).parent / "resumenes"


def generar(conn: sqlite3.Connection, mes: str, hoy: date) -> str:
    """Resumen del mes en Markdown."""
    r = metricas.resumen_mes(conn, mes, hoy)
    monto = formato.formatear_monto
    lineas = [f"# Resumen de {formato.nombre_mes(mes)}", "", "| | |", "|---|---|"]
    lineas.append(f"| Gasto | {monto(r.gasto)} |")
    ingresos = monto(r.ingresos)
    if r.ingresos_extraordinarios:
        ingresos = f"{ingresos} (incluye {monto(r.ingresos_extraordinarios)} extraordinarios)"
    lineas.append(f"| Ingresos | {ingresos} |")
    lineas.append(f"| Balance | {monto(r.balance)} |")
    lineas.append(f"| Tasa de ahorro | {formato.porcentaje(r.tasa_ahorro)} |")
    lineas.append(f"| Promedio diario | {monto(r.promedio_diario)} |")
    anterior = monto(r.gasto_anterior)
    if r.variacion_gasto is not None:
        signo = ""
        if r.variacion_gasto > 0:
            signo = "+"
        anterior = f"{anterior} (variación {signo}{formato.porcentaje(r.variacion_gasto)})"
    lineas.append(f"| Gasto del mes anterior | {anterior} |")
    lineas.append("")
    lineas.append(
        f"Aparte (no cuentan como gasto): transferencias {monto(r.transferencias)}, "
        f"reembolsables {monto(r.reembolsables)}."
    )
    if r.usd_gasto_sin_convertir or r.usd_ingresos_sin_convertir:
        lineas.append(
            f"En dólares sin convertir: gasto {monto(r.usd_gasto_sin_convertir, 'USD')}, "
            f"ingresos {monto(r.usd_ingresos_sin_convertir, 'USD')}."
        )

    lineas.extend(["", "## Por categoría", ""])
    for i in range(len(r.por_categoria)):
        nombre, valor, parte = r.por_categoria[i]
        lineas.append(f"- {nombre}: {monto(valor)} ({formato.porcentaje(parte)})")

    presupuestos = metricas.estado_presupuestos(conn, mes)
    if presupuestos:
        lineas.extend(["", "## Presupuestos", ""])
        for i in range(len(presupuestos)):
            p = presupuestos[i]
            marca = ""
            if p.nivel == "excedido":
                marca = " — excedido"
            elif p.nivel == "alerta":
                marca = " — cerca del límite"
            lineas.append(
                f"- {p.nombre}: {monto(p.gastado)} de {monto(p.presupuesto)} "
                f"({formato.porcentaje(p.proporcion)}){marca}"
            )

    grandes = metricas.gastos_mas_grandes(conn, mes, 5)
    if grandes:
        lineas.extend(["", "## Gastos más grandes", ""])
        for i in range(len(grandes)):
            lineas.append(f"{i + 1}. {formato.fecha_corta(grandes[i].fecha_hora)} · {grandes[i].nombre} · {monto(grandes[i].monto)}")

    activas = suscripciones.detectar(conn, hoy)
    if activas:
        lineas.extend(["", "## Suscripciones activas", ""])
        for i in range(len(activas)):
            lineas.append(
                f"- {activas[i].comercio}: {monto(activas[i].monto_tipico, activas[i].moneda)} "
                f"(próximo cobro estimado {activas[i].proximo_cobro.strftime('%d/%m/%Y')})"
            )
    return "\n".join(lineas) + "\n"


def mensual(conn: sqlite3.Connection, ruta_db, hoy: date) -> Path | None:
    """Escribe el resumen del mes anterior si falta y hay datos. Devuelve la ruta creada o None."""
    mes = formato.mes_desplazado(formato.mes_de(hoy), -1)
    archivo = carpeta_resumenes(ruta_db) / f"{mes}.md"
    if archivo.exists():
        return None
    inicio, fin = formato.rango_mes(mes)
    hay = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE estado != 'ignorada' AND fecha_hora >= ? AND fecha_hora < ?",
        (inicio, fin),
    ).fetchone()[0]
    if hay == 0:
        return None
    archivo.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    archivo.write_text(generar(conn, mes, hoy), encoding="utf-8")
    r = metricas.resumen_mes(conn, mes, hoy)
    notificar(
        f"Finanzas: resumen de {formato.nombre_mes(mes)}",
        f"Gasto {formato.formatear_monto(r.gasto)}, ingresos {formato.formatear_monto(r.ingresos)}, "
        f"ahorro {formato.porcentaje(r.tasa_ahorro)}. Detalle en {archivo}",
    )
    return archivo
