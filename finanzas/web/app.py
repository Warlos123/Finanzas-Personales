"""UI web local: FastAPI + plantillas Jinja2 con formularios HTML (sin JavaScript de terceros).

Solo escucha en 127.0.0.1. Para que otras páginas abiertas en el navegador no puedan leerla
ni modificarla (DNS rebinding / CSRF), se exige un Host local y, en los POST, un Origin local.
"""

import csv
import hashlib
import io
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from finanzas import (
    alertas, catalogos, db, estado_cuenta, formato, graficos, ingesta, metricas, movimientos,
    reconciliacion, recurrentes, reglas, suscripciones, tipo_cambio,
)
from finanzas.tiempo import ZONA_CR, ahora_iso

PUERTO = 8765
DIR_WEB = Path(__file__).parent
TAMANO_MAXIMO_PDF = 10 * 1024 * 1024


def _hoy():
    return datetime.now(ZONA_CR).date()


def _entero_opcional(valor) -> int | None:
    if valor is None or str(valor).strip() == "":
        return None
    return int(valor)


def _texto_opcional(valor) -> str | None:
    if valor is None:
        return None
    valor = str(valor).strip()
    if valor == "":
        return None
    return valor


def _redirigir(ruta: str, msg: str | None = None, error: str | None = None) -> RedirectResponse:
    parametros = {}
    if msg:
        parametros["msg"] = msg
    if error:
        parametros["error"] = error
    if parametros:
        separador = "?"
        if "?" in ruta:
            separador = "&"
        ruta = ruta + separador + urlencode(parametros)
    return RedirectResponse(ruta, status_code=303)


def _ruta_interna(valor: str | None, por_defecto: str) -> str:
    """Solo rutas locales ('/...'), para no enlazar a otro sitio ni a `javascript:`."""
    if valor is None or not valor.startswith("/") or valor.startswith("//"):
        return por_defecto
    return valor


def _mes_pedido(request: Request) -> str:
    mes = request.query_params.get("mes")
    if formato.mes_valido(mes):
        return mes
    return formato.mes_de(_hoy())


def _filtros(request: Request) -> movimientos.Filtros:
    """Filtros de la lista de transacciones a partir de la URL (mes vacío = todas las fechas)."""
    parametros = request.query_params
    filtros = movimientos.Filtros(
        mes=parametros.get("mes", formato.mes_de(_hoy())),
        cuenta_id=_entero_opcional(parametros.get("cuenta")),
        categoria=_texto_opcional(parametros.get("categoria")),
        tipo=_texto_opcional(parametros.get("tipo")),
        texto=_texto_opcional(parametros.get("q")),
        incluir_ignoradas=parametros.get("ignoradas") == "1",
    )
    if not formato.mes_valido(filtros.mes):
        filtros.mes = None
    return filtros


_COLUMNAS_CSV = (
    "fecha_hora", "cuenta", "comercio_o_destinatario", "descripcion", "categoria", "tipo",
    "monto", "moneda", "estado", "extraordinario", "notas",
)


def _csv_transacciones(filas: list) -> str:
    """CSV con BOM UTF-8 (para que Excel y LibreOffice muestren bien las tildes)."""
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(_COLUMNAS_CSV)
    for i in range(len(filas)):
        t = filas[i]
        escritor.writerow((
            t["fecha_hora"], t["cuenta_nombre"], t["comercio_o_destinatario"], t["descripcion"],
            t["categoria_nombre"], t["tipo"], formato.centimos_a_texto(t["monto_centimos"]),
            t["moneda"], t["estado"], t["extraordinario"], t["notas"],
        ))
    return "\ufeff" + salida.getvalue()


def _datos_transaccion(formulario, actual=None) -> movimientos.DatosTransaccion:
    """Arma DatosTransaccion desde un formulario. Lanza ValueError con un mensaje para mostrar."""
    estado = formulario.get("estado")
    if not estado:
        estado = "confirmada"
        if actual is not None:
            estado = actual["estado"]
    return movimientos.DatosTransaccion(
        fecha_hora=formato.fecha_desde_formulario(formulario.get("fecha", "")),
        monto_centimos=formato.monto_desde_texto(formulario.get("monto", "")),
        moneda=formulario.get("moneda", "CRC"),
        tipo=formulario.get("tipo", "gasto"),
        cuenta_id=_entero_opcional(formulario.get("cuenta_id")),
        categoria_id=_entero_opcional(formulario.get("categoria_id")),
        comercio_o_destinatario=_texto_opcional(formulario.get("comercio")),
        notas=_texto_opcional(formulario.get("notas")),
        estado=estado,
        extraordinario=formulario.get("extraordinario") == "1",
    )


def crear_app(ruta_db, puerto: int = PUERTO) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=DIR_WEB / "static"), name="static")
    plantillas = Jinja2Templates(directory=DIR_WEB / "templates")
    plantillas.env.filters["monto"] = formato.formatear_monto
    plantillas.env.filters["fecha_corta"] = formato.fecha_corta
    plantillas.env.filters["fecha_dia"] = formato.fecha_dia
    plantillas.env.filters["fecha_form"] = formato.fecha_a_formulario
    plantillas.env.filters["centimos_texto"] = formato.centimos_a_texto
    plantillas.env.filters["porcentaje"] = formato.porcentaje
    plantillas.env.filters["nombre_mes"] = formato.nombre_mes
    # Versión del CSS en la URL: si el archivo cambia, el navegador no usa la copia en caché.
    contenido_css = (DIR_WEB / "static" / "estilo.css").read_bytes()
    plantillas.env.globals["version_css"] = hashlib.sha256(contenido_css).hexdigest()[:10]

    hosts_locales = (f"127.0.0.1:{puerto}", f"localhost:{puerto}")
    origenes_locales = (f"http://127.0.0.1:{puerto}", f"http://localhost:{puerto}")

    @app.middleware("http")
    async def solo_local(request: Request, call_next):
        if request.headers.get("host") not in hosts_locales:
            return PlainTextResponse("Host no permitido", status_code=400)
        if request.method not in ("GET", "HEAD") and request.headers.get("origin") not in origenes_locales:
            return PlainTextResponse("Origen no permitido", status_code=403)
        return await call_next(request)

    @contextmanager
    def abrir():
        conn = db.conectar(ruta_db)
        try:
            yield conn
        finally:
            conn.close()

    def mostrar(request: Request, conn, plantilla: str, seccion: str, **contexto):
        contexto["seccion"] = seccion
        contexto["pendientes"] = movimientos.contar_bandeja(conn)
        contexto["msg"] = request.query_params.get("msg")
        contexto["error"] = request.query_params.get("error")
        return plantillas.TemplateResponse(request, plantilla, contexto)

    # --- Dashboard ---

    @app.get("/")
    def dashboard(request: Request):
        mes = _mes_pedido(request)
        with abrir() as conn:
            with conn:
                recurrentes.generar(conn, _hoy())
            resumen = metricas.resumen_mes(conn, mes, _hoy())
            return mostrar(
                request, conn, "dashboard.html", "dashboard", r=resumen,
                anterior=formato.mes_desplazado(mes, -1), siguiente=formato.mes_desplazado(mes, 1),
                hay_tipo_cambio=metricas.tipo_cambio(conn) is not None,
                sinc=alertas.estado(conn, datetime.now(ZONA_CR)),
                presupuestos=metricas.estado_presupuestos(conn, mes),
                suscripciones=suscripciones.detectar(conn, _hoy()),
            )

    # --- Gráficos ---

    @app.get("/graficos")
    def pagina_graficos(request: Request):
        mes = _mes_pedido(request)
        with abrir() as conn:
            datos = graficos.gasto_por_mes(conn, mes)
            # Clic en una columna: ?detalle=AAAA-MM elige el mes de los gastos más grandes (dentro de los 12).
            detalle = mes
            pedido = request.query_params.get("detalle")
            for i in range(len(datos)):
                if datos[i][0] == pedido:
                    detalle = pedido
            return mostrar(
                request, conn, "graficos.html", "graficos", mes=mes, detalle=detalle,
                g=graficos.grafico_meses(datos, detalle), grandes=metricas.gastos_mas_grandes(conn, detalle, 10),
                es_mes_actual=mes == formato.mes_de(_hoy()),
                hay_tipo_cambio=metricas.tipo_cambio(conn) is not None,
                anterior=formato.mes_desplazado(mes, -1), siguiente=formato.mes_desplazado(mes, 1),
            )

    # --- Transacciones ---

    @app.get("/transacciones")
    def transacciones(request: Request):
        filtros = _filtros(request)
        with abrir() as conn:
            return mostrar(
                request, conn, "transacciones.html", "transacciones",
                filas=movimientos.listar(conn, filtros), f=filtros,
                cuentas=catalogos.cuentas(conn), categorias=catalogos.categorias(conn),
                tipos=movimientos.TIPOS,
            )

    @app.get("/transacciones.csv")
    def exportar_csv(request: Request):
        filtros = _filtros(request)
        with abrir() as conn:
            filas = movimientos.listar(conn, filtros, limite=1_000_000)
        nombre = "transacciones-todas.csv"
        if filtros.mes:
            nombre = f"transacciones-{filtros.mes}.csv"
        return Response(
            _csv_transacciones(filas),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )

    @app.get("/transacciones/{transaccion_id}")
    def transaccion(request: Request, transaccion_id: int):
        with abrir() as conn:
            fila = movimientos.obtener(conn, transaccion_id)
            if fila is None:
                return _redirigir("/transacciones", error="No existe esa transacción")
            return mostrar(
                request, conn, "transaccion.html", "transacciones", t=fila,
                cuentas=catalogos.cuentas(conn), categorias=catalogos.categorias(conn),
                tipos=movimientos.TIPOS, estados=movimientos.ESTADOS, monedas=movimientos.MONEDAS,
                volver=_ruta_interna(request.query_params.get("volver"), "/transacciones"),
            )

    @app.post("/transacciones/{transaccion_id}")
    async def guardar_transaccion(request: Request, transaccion_id: int):
        formulario = await request.form()
        ruta = f"/transacciones/{transaccion_id}"
        with abrir() as conn:
            actual = movimientos.obtener(conn, transaccion_id)
            if actual is None:
                return _redirigir("/transacciones", error="No existe esa transacción")
            try:
                datos = _datos_transaccion(formulario, actual)
                with conn:
                    movimientos.actualizar(conn, transaccion_id, datos)
            except ValueError as error:
                return _redirigir(ruta, error=str(error))
        return _redirigir(ruta, msg="Guardado")

    @app.post("/transacciones/{transaccion_id}/borrar")
    def borrar_transaccion(transaccion_id: int):
        with abrir() as conn:
            try:
                with conn:
                    resultado = movimientos.borrar(conn, transaccion_id)
            except ValueError as error:
                return _redirigir(f"/transacciones/{transaccion_id}", error=str(error))
        return _redirigir("/ingresos", msg=f"Transacción {resultado}")

    # --- Bandeja de pendientes ---

    @app.get("/bandeja")
    def bandeja(request: Request):
        with abrir() as conn:
            filas = movimientos.bandeja(conn)
            campos = []
            for i in range(len(filas)):
                campos.append(reglas.campo_principal(filas[i]["cuenta_tipo"]))
            return mostrar(
                request, conn, "bandeja.html", "bandeja", filas=filas, campos=campos,
                errores=movimientos.errores_de_parseo(conn), categorias=catalogos.categorias(conn),
                tipos=movimientos.TIPOS,
            )

    @app.post("/bandeja")
    async def decidir(request: Request):
        """Guarda de una vez todas las filas con decisión (categoría, tipo distinto de gasto o
        "ignorar"). Primero las elecciones a mano, después las reglas nuevas sobre el resto."""
        formulario = await request.form()
        ids = formulario.getlist("id")
        guardadas = 0
        ignoradas = 0
        reglas_creadas = 0
        otras = 0
        problemas = []
        with abrir() as conn:
            try:
                with conn:
                    for i in range(len(ids)):
                        transaccion_id = int(ids[i])
                        sufijo = f"_{transaccion_id}"
                        if formulario.get("ignorar" + sufijo) == "1":
                            movimientos.ignorar(conn, transaccion_id)
                            ignoradas += 1
                            continue
                        categoria_id = _entero_opcional(formulario.get("categoria" + sufijo))
                        tipo = formulario.get("tipo" + sufijo, "gasto")
                        if categoria_id is None and tipo == "gasto":
                            continue
                        movimientos.categorizar(conn, transaccion_id, categoria_id, tipo)
                        guardadas += 1
                        if formulario.get("regla" + sufijo) != "1":
                            continue
                        tipo_forzado = None
                        if tipo != "gasto":
                            tipo_forzado = tipo
                        try:
                            reglas.crear_regla(
                                conn, formulario.get("campo" + sufijo, ""),
                                formulario.get("patron" + sufijo, ""), categoria_id, tipo_forzado,
                            )
                            reglas_creadas += 1
                        except ValueError as error:
                            problemas.append(str(error))
                    if reglas_creadas:
                        otras = reglas.aplicar_reglas(conn)
            except ValueError as error:
                return _redirigir("/bandeja", error=str(error))
        if guardadas == 0 and ignoradas == 0:
            return _redirigir("/bandeja", error="No elegiste ninguna categoría (a los gastos les hace falta una)")
        partes = [f"{guardadas} guardadas"]
        if reglas_creadas:
            partes.append(f"{reglas_creadas} reglas nuevas que categorizaron {otras} transacciones más")
        if ignoradas:
            partes.append(f"{ignoradas} ignoradas")
        error = None
        if problemas:
            error = "Reglas no creadas: " + "; ".join(problemas)
        return _redirigir("/bandeja", msg=", ".join(partes), error=error)

    @app.post("/reprocesar")
    def reprocesar():
        with abrir() as conn:
            resumen = ingesta.reprocesar(conn)
        return _redirigir(
            "/bandeja", msg=f"Reprocesado: {resumen.nuevas} nuevas, {resumen.existentes} existentes"
        )

    # --- Ingresos ---

    @app.get("/ingresos")
    def ingresos(request: Request):
        mes = _mes_pedido(request)
        with abrir() as conn:
            with conn:
                recurrentes.generar(conn, _hoy())
            filas = movimientos.listar(conn, movimientos.Filtros(mes=mes, tipo="ingreso"))
            lista_recurrentes = conn.execute(
                "SELECT * FROM recurring_incomes ORDER BY activa DESC, nombre"
            ).fetchall()
            return mostrar(
                request, conn, "ingresos.html", "ingresos", mes=mes, filas=filas,
                recurrentes=lista_recurrentes, cuentas=catalogos.cuentas(conn),
                monedas=movimientos.MONEDAS, hoy=_hoy().isoformat(),
                anterior=formato.mes_desplazado(mes, -1), siguiente=formato.mes_desplazado(mes, 1),
            )

    @app.post("/ingresos")
    async def crear_ingreso(request: Request):
        formulario = await request.form()
        try:
            datos = _datos_transaccion(formulario)
            datos.tipo = "ingreso"
            with abrir() as conn:
                with conn:
                    movimientos.crear_manual(conn, datos)
        except ValueError as error:
            return _redirigir("/ingresos", error=str(error))
        return _redirigir("/ingresos?mes=" + datos.fecha_hora[:7], msg="Ingreso agregado")

    async def _guardar_recurrente(request: Request, recurrente_id: int | None):
        formulario = await request.form()
        try:
            with abrir() as conn:
                with conn:
                    recurrentes.guardar(
                        conn, recurrente_id, formulario.get("nombre", ""),
                        formato.monto_desde_texto(formulario.get("monto", "")),
                        formulario.get("moneda", "CRC"), int(formulario.get("dia", "0")),
                        _entero_opcional(formulario.get("cuenta_id")),
                        formulario.get("activa") == "1", _texto_opcional(formulario.get("desde")),
                    )
                    creados = recurrentes.generar(conn, _hoy())
        except ValueError as error:
            return _redirigir("/ingresos", error=str(error))
        return _redirigir("/ingresos", msg=f"Recurrente guardado; {creados} ingresos generados")

    @app.post("/recurrentes")
    async def crear_recurrente(request: Request):
        return await _guardar_recurrente(request, None)

    @app.post("/recurrentes/{recurrente_id}")
    async def editar_recurrente(request: Request, recurrente_id: int):
        return await _guardar_recurrente(request, recurrente_id)

    @app.post("/recurrentes/{recurrente_id}/borrar")
    def borrar_recurrente(recurrente_id: int):
        with abrir() as conn:
            with conn:
                recurrentes.borrar(conn, recurrente_id)
        return _redirigir("/ingresos", msg="Recurrente borrado (los ingresos ya generados se quedan)")

    # --- Reconciliación con el estado de cuenta ---

    @app.get("/reconciliar")
    def lista_estados(request: Request):
        with abrir() as conn:
            return mostrar(request, conn, "reconciliar.html", "reconciliar", estados=reconciliacion.listar(conn))

    @app.post("/reconciliar")
    async def subir_estado(request: Request):
        formulario = await request.form()
        archivo = formulario.get("archivo")
        if archivo is None or isinstance(archivo, str):
            return _redirigir("/reconciliar", error="Elige el PDF del estado de cuenta")
        contenido = await archivo.read(TAMANO_MAXIMO_PDF + 1)
        if len(contenido) > TAMANO_MAXIMO_PDF:
            return _redirigir("/reconciliar", error="El archivo es demasiado grande")
        try:
            texto = estado_cuenta.texto_de_pdf(contenido)
            with abrir() as conn:
                with conn:
                    estado_id = reconciliacion.guardar(conn, texto)
        except ValueError as error:
            return _redirigir("/reconciliar", error=str(error))
        return _redirigir(f"/reconciliar/{estado_id}")

    @app.get("/reconciliar/{estado_id}")
    def ver_reconciliacion(request: Request, estado_id: int):
        with abrir() as conn:
            estado = reconciliacion.obtener(conn, estado_id)
            if estado is None:
                return _redirigir("/reconciliar", error="Ese estado de cuenta no existe")
            return mostrar(
                request, conn, "reconciliacion.html", "reconciliar", estado_id=estado_id,
                r=reconciliacion.reconciliar(conn, estado), tipos=movimientos.TIPOS,
            )

    @app.post("/reconciliar/{estado_id}")
    async def agregar_desde_estado(request: Request, estado_id: int):
        formulario = await request.form()
        indices = formulario.getlist("indice")
        elecciones = []
        for i in range(len(indices)):
            if formulario.get(f"agregar_{indices[i]}") == "1":
                elecciones.append((int(indices[i]), formulario.get(f"tipo_{indices[i]}", "")))
        ruta = f"/reconciliar/{estado_id}"
        try:
            with abrir() as conn:
                estado = reconciliacion.obtener(conn, estado_id)
                if estado is None:
                    return _redirigir("/reconciliar", error="Ese estado de cuenta no existe")
                with conn:
                    agregadas, ignoradas = reconciliacion.agregar(conn, estado, elecciones)
        except ValueError as error:
            return _redirigir(ruta, error=str(error))
        return _redirigir(ruta, msg=f"{agregadas} agregadas, {ignoradas} ignoradas")

    # --- Reglas ---

    @app.get("/reglas")
    def lista_reglas(request: Request):
        with abrir() as conn:
            filas = conn.execute("SELECT * FROM rules ORDER BY prioridad, id").fetchall()
            return mostrar(
                request, conn, "reglas.html", "reglas", filas=filas,
                categorias=catalogos.categorias(conn), campos=reglas.CAMPOS, tipos=movimientos.TIPOS,
            )

    async def _guardar_regla(request: Request, regla_id: int | None):
        formulario = await request.form()
        try:
            with abrir() as conn:
                with conn:
                    argumentos = (
                        formulario.get("campo", ""), formulario.get("patron", ""),
                        _entero_opcional(formulario.get("categoria_id")),
                        _texto_opcional(formulario.get("tipo_forzado")),
                    )
                    prioridad = _entero_opcional(formulario.get("prioridad"))
                    if regla_id is None:
                        reglas.crear_regla(conn, *argumentos, prioridad=prioridad)
                    else:
                        if prioridad is None:
                            prioridad = 0
                        reglas.actualizar_regla(conn, regla_id, *argumentos, prioridad)
                    cambiadas = reglas.aplicar_reglas(conn)
        except ValueError as error:
            return _redirigir("/reglas", error=str(error))
        return _redirigir("/reglas", msg=f"Regla guardada; {cambiadas} transacciones categorizadas")

    @app.post("/reglas")
    async def crear_regla(request: Request):
        return await _guardar_regla(request, None)

    @app.post("/reglas/aplicar")
    def aplicar_reglas():
        with abrir() as conn:
            with conn:
                cambiadas = reglas.aplicar_reglas(conn)
        return _redirigir("/reglas", msg=f"{cambiadas} transacciones categorizadas")

    @app.post("/reglas/{regla_id}")
    async def editar_regla(request: Request, regla_id: int):
        return await _guardar_regla(request, regla_id)

    @app.post("/reglas/{regla_id}/borrar")
    def borrar_regla(regla_id: int):
        with abrir() as conn:
            with conn:
                reglas.borrar_regla(conn, regla_id)
        return _redirigir("/reglas", msg="Regla borrada")

    # --- Cuentas, categorías y tipo de cambio ---

    @app.get("/cuentas")
    def cuentas(request: Request):
        with abrir() as conn:
            return mostrar(
                request, conn, "cuentas.html", "cuentas", cuentas=catalogos.cuentas(conn),
                categorias=catalogos.categorias(conn), tipos_cuenta=catalogos.TIPOS_CUENTA,
                presupuestos=catalogos.presupuestos(conn),
                monedas=movimientos.MONEDAS,
                tipo_cambio=db.leer_ajuste(conn, metricas.AJUSTE_TIPO_CAMBIO, ""),
                tipo_cambio_actualizado=db.leer_ajuste(conn, tipo_cambio.AJUSTE_ACTUALIZADO),
            )

    async def _guardar_cuenta(request: Request, cuenta_id: int | None):
        formulario = await request.form()
        try:
            with abrir() as conn:
                with conn:
                    catalogos.guardar_cuenta(
                        conn, cuenta_id, formulario.get("nombre", ""), formulario.get("tipo", ""),
                        formulario.get("ultimos4"), formulario.get("moneda", "CRC"),
                    )
        except ValueError as error:
            return _redirigir("/cuentas", error=str(error))
        return _redirigir("/cuentas", msg="Cuenta guardada")

    @app.post("/cuentas")
    async def crear_cuenta(request: Request):
        return await _guardar_cuenta(request, None)

    @app.post("/cuentas/{cuenta_id}")
    async def editar_cuenta(request: Request, cuenta_id: int):
        return await _guardar_cuenta(request, cuenta_id)

    async def _guardar_categoria(request: Request, categoria_id: int | None):
        formulario = await request.form()
        try:
            with abrir() as conn:
                with conn:
                    guardada = catalogos.guardar_categoria(
                        conn, categoria_id, formulario.get("nombre", ""),
                        _entero_opcional(formulario.get("padre_id")),
                    )
                    texto_presupuesto = _texto_opcional(formulario.get("presupuesto"))
                    presupuesto = None
                    if texto_presupuesto is not None:
                        presupuesto = formato.monto_desde_texto(texto_presupuesto)
                    catalogos.guardar_presupuesto(conn, guardada, presupuesto)
        except ValueError as error:
            return _redirigir("/cuentas", error=str(error))
        return _redirigir("/cuentas", msg="Categoría guardada")

    @app.post("/categorias")
    async def crear_categoria(request: Request):
        return await _guardar_categoria(request, None)

    @app.post("/categorias/{categoria_id}")
    async def editar_categoria(request: Request, categoria_id: int):
        return await _guardar_categoria(request, categoria_id)

    @app.post("/categorias/{categoria_id}/borrar")
    def borrar_categoria(categoria_id: int):
        with abrir() as conn:
            with conn:
                catalogos.borrar_categoria(conn, categoria_id)
        return _redirigir("/cuentas", msg="Categoría borrada; sus transacciones volvieron a la bandeja")

    @app.post("/ajustes/tipo-cambio")
    async def guardar_tipo_cambio(request: Request):
        formulario = await request.form()
        valor = _texto_opcional(formulario.get("tipo_cambio"))
        with abrir() as conn:
            with conn:
                db.guardar_ajuste(conn, metricas.AJUSTE_TIPO_CAMBIO, valor)
            if valor is not None and metricas.tipo_cambio(conn) is None:
                with conn:
                    db.guardar_ajuste(conn, metricas.AJUSTE_TIPO_CAMBIO, None)
                return _redirigir("/cuentas", error="Tipo de cambio inválido (ej. 505.50)")
            # Cuenta como la actualización del día: Hacienda no lo pisa hasta mañana.
            with conn:
                db.guardar_ajuste(conn, tipo_cambio.AJUSTE_ACTUALIZADO, ahora_iso())
        return _redirigir("/cuentas", msg="Tipo de cambio guardado")

    return app
