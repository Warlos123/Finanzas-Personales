# CLAUDE.md

App personal de finanzas (un usuario, Costa Rica). Todo local: la PC importa correos BCR (IMAP) y SMS SINPE (JSON vía Syncthing desde Android) a SQLite. Ver el diseño completo en las instrucciones originales del proyecto (secciones 1–11).

## Reglas de trabajo

- Trabajar por etapas; al cerrar cada una: resumir, actualizar este archivo y esperar confirmación.
- Cambios mínimos, commits pequeños. No agregar funciones no pedidas.
- Estilo: **sin operador ternario** (`x if c else y`) y **bucles `for` indexados** (`for i in range(len(xs))`) en vez de iterar la colección o usar comprehensions. Excepción: en plantillas Jinja se usa `{% for x in xs %}` (lo idiomático ahí).
- Si falta un formato o algo es ambiguo: preguntar antes de inventar.
- Fixtures siempre sanitizados (datos ficticios). Nada real en el repo.
- Privacidad: nunca loguear cuerpos de SMS, nombres de destinatarios ni números de teléfono. Los mensajes de `ErrorParseo` y avisos tampoco los incluyen.
- Gmail solo por IMAP + contraseña de aplicación (no OAuth / Google Cloud). Solo lectura: `readonly=True`, `BODY.PEEK[]`.

## Arquitectura (PC)

```
finanzas/
  tiempo.py            ZONA_CR y ahora_iso()
  db.py                conectar() (WAL, foreign_keys) + migrar() por PRAGMA user_version
  migrations/NNNN_*.sql  migraciones numeradas, se aplican en orden
  parsers/
    base.py            ErrorParseo, TransaccionParseada, ResultadoParseo, monto/moneda
    bcr_email.py       correo "BCR Tarjetas" (HTML)
    sinpe_sms.py       SMS SINPE enviado (4066)
    __init__.py        PARSERS: fuente -> parsear(contenido, recibido_en)
  ingesta.py           registrar_evento, procesar_evento, importar_evento, reprocesar
  llavero.py           contraseña de Gmail en libsecret vía `secret-tool` (por stdin)
  notificar.py         notify-send
  gmail.py             importador IMAP solo lectura + configurar()
  cli.py, __main__.py  comando `finanzas` (configurar-gmail, importar, reprocesar, ui)
  reglas.py            reglas de categorización (buscar, aplicar, crear/editar/borrar)
  movimientos.py       consultas y cambios de transacciones para la UI (filtros, bandeja, edición)
  recurrentes.py       ingresos recurrentes → un ingreso por mes
  metricas.py          dashboard mensual
  catalogos.py         cuentas y categorías
  formato.py           montos, fechas y meses para mostrar/leer formularios
  web/app.py           FastAPI: crear_app(ruta_db, puerto); middleware solo-local
  web/templates/       Jinja2 (macros.html con los <select>)
  web/static/estilo.css  claro/oscuro según el sistema
systemd/               finanzas-importar.service.in + .timer (cada 5 min), finanzas-ui.service.in
scripts/instalar_systemd.sh  instala las unidades de usuario con la ruta del venv
scripts/abrir_ui.sh    arranca la UI si hace falta y la abre: 1) ventana propia `scripts/ventana.py` (GTK4 +
                       WebKitGTK, Python del sistema, app_id `cr.finanzas.Finanzas`, una sola instancia);
                       2) `--app` en un navegador Chromium; 3) ventana nueva de Firefox; 4) xdg-open.
                       La PC usa Firefox y la opción 1 (elegida por el usuario, funciona). Atajo SUPER+CTRL+SHIFT+F;
                       Omarchy usa config Lua: `o.bind("SUPER + CTRL + SHIFT + F", "Finanzas", "<repo>/scripts/abrir_ui.sh")`)
android/               app Kotlin mínima (ver android/README.md)
  app/src/main/java/cr/finanzas/sms/
    Sms4066.kt         reglas puras: remitente, comprobante, fecha ISO, JSON (probadas en la JVM)
    ReceptorSms.kt     BroadcastReceiver SMS_RECEIVED (protegido con BROADCAST_SMS)
    Entrega.kt         escribe <comprobante>.json por SAF; si falla, cola + WorkManager
    Cola.kt            SQLite local: pendientes (con cuerpo) y exportados (solo ids)
    TrabajoReintento.kt  Worker con backoff exponencial
    Backfill.kt        bandeja de entrada del 4066
    MainActivity.kt    pantalla única (carpeta, permisos, último, pendientes, backfill, batería)
tests/
  fixtures/bcr/*.html  correos sanitizados
  fixtures/sms/*.json  eventos en el esquema JSON del teléfono (schema_version 1)
```

## Decisiones tomadas

- **Montos** en céntimos enteros (`monto_centimos`), siempre positivos; el signo lo da `tipo`.
- **Fechas** en TEXT ISO 8601 con offset (`2026-10-26T08:43:33-06:00`).
- **raw_events** guarda siempre el original (HTML del correo o cuerpo del SMS). Columnas extra respecto al diseño: `estado_parseo` (`sin_procesar|ok|con_avisos|error`), `detalle_parseo`, `procesado_en`, `creado_en`. Ahí se marcan filas no aprobadas, monedas desconocidas y errores.
- **Deduplicación**: `raw_events` UNIQUE(fuente, hash sha256). `transactions.llave_unica` UNIQUE con prefijo: `bcr:<autorizacion>:<no_referencia>`, `sinpe:<comprobante>`. Manuales: NULL.
- **Reproceso** = upsert por `llave_unica`. No pisa transacciones con `editada_en`; nunca toca tipo, categoría ni notas; el estado solo cambia si estaba `pendiente`.
- **Correo BCR**: columnas ubicadas por texto del encabezado (sin tildes/puntos), tablas anidadas y celdas sin cerrar soportadas. Solo `Aprobada` crea transacción; otros estados → aviso en raw_events. Si una fila aprobada no se puede interpretar, falla el correo completo (`error`) para reprocesarlo tras arreglar el parser.
- **Moneda**: texto con "colon" → CRC (real: `COLON COSTA RICA`), con "dollar"/"dolar" → USD (real: `US DOLLAR`). Sin tildes ni mayúsculas. Otro → `moneda` NULL, estado `pendiente` y aviso.
- **SMS SINPE**: fecha = primeros 8 dígitos del comprobante; hora = `received_at` convertido a hora de CR. `received_at` debe traer offset (si no, error). Descripción sin el relleno de asteriscos; vacía → NULL.
- **Cuentas** se crean solas: `Tarjeta BCR ****NNNN` por últimos 4 dígitos; una única `SINPE Móvil`. Moneda por defecto CRC.
- Tipo por defecto de lo importado: `gasto` (las reglas lo ajustarán en la Etapa 2).
- **Base de datos** por defecto en `$XDG_DATA_HOME/finanzas/finanzas.db` (`~/.local/share/...`); `--db` la cambia.
- **Llavero**: `secret-tool` (CLI de libsecret) en vez de la librería `keyring`, para no agregar dependencias. Atributos `service=finanzas-gmail usuario=<correo>`. El usuario de Gmail se guarda en `settings.gmail_usuario`.
- **IMAP**: carpeta con flag `\All` ("Todos", incluye archivados); búsqueda `FROM bcrtarjestcta@bancobcr.com SUBJECT "Transacciones"`. Estado en `settings`: `imap_uidvalidity:<carpeta>` e `imap_ultimo_uid:<carpeta>`. Primera corrida (o UIDVALIDITY nuevo): backfill de 180 días con `SINCE`; `importar --desde AAAA-MM-DD` recorre desde una fecha.
- **Credenciales rechazadas**: se guarda `settings.gmail_credenciales_invalidas`, se notifica una vez y las corridas siguientes no se conectan hasta correr `configurar-gmail` de nuevo. Errores de red: solo log; el timer reintenta en 5 min.
- Códigos de salida de `importar`: 0 ok, 1 sin configurar/llavero, 2 credenciales, 3 red/IMAP.
- Logs a stderr (journald con systemd); solo conteos y UIDs, nunca contenido.
- **UI**: FastAPI + Jinja2 con formularios HTML y POST→redirect (sin HTMX ni JS de terceros; solo un `onchange` y `confirm()` inline). Puerto 8765, siempre `127.0.0.1`. Middleware: Host debe ser `127.0.0.1:8765`/`localhost:8765` y los POST deben traer Origin local (evita DNS rebinding y CSRF desde otras pestañas). `?volver=` solo acepta rutas internas.
- **Reglas**: patrón "contiene", sin tildes ni mayúsculas. `comercio` aplica a cuentas no SINPE, `destinatario` a SINPE, `descripcion` a la descripción. Orden por `prioridad` ascendente; gana la primera. Solo tocan transacciones sin categoría, sin `editada_en` y no ignoradas. Se aplican al importar (nuevas) y al crear/editar reglas (todas las candidatas).
- **Bandeja**: gastos sin categoría + transacciones `pendiente` (no ignoradas), una fila por comercio/destinatario con el conteo de iguales. Las `Negada` quedan fuera (no son transacciones). Categorizar desde la bandeja no marca `editada_en`; la edición completa sí (y entonces el reproceso no la pisa).
- **Ingresos manuales**: transacción `ingreso` sin llave; la fuente va en `comercio_o_destinatario`; `extraordinario` = 1 para bonos/aguinaldo. Solo las manuales se borran; las importadas se ignoran.
- **Recurrentes**: llave `recurrente:<id>:<AAAA-MM>`, desde `recurring_incomes.desde`; día 31 → último día del mes. Se generan al abrir el dashboard o Ingresos. "Borrar" uno generado lo deja ignorado (si no, se regeneraría).
- **Métricas**: todo en CRC. USD se convierte con `settings.tipo_cambio_usd` si existe; si no, se muestra aparte. Transferencias y reembolsables aparte. La comparación con el mes anterior usa la proyección en el mes en curso.
- **Android**: Kotlin sin AppCompat ni Compose (Activity del framework + XML); dependencias: documentfile y work-runtime. minSdk 31, targetSdk 35. Sin permiso INTERNET. Solo exporta SMS entrantes del 4066 que traen `Comprobante <dígitos>`; los demás se descartan sin guardarse. `received_at` = hora de llegada al teléfono (en vivo `currentTimeMillis`, en backfill la columna `date` de la bandeja). Intenta escribir directo y, si falla, cola + WorkManager (`vaciar-cola`, KEEP, backoff 30 s). La tabla `exportados` evita archivos duplicados aunque la PC mueva los JSON. Firma desde `android/firma.properties` (fuera de git).
- **Se mantiene el teléfono** (decisión del usuario, 27-oct-2026): se evaluó capturar los SINPE solo por correo. El BCR sí manda "SINPEMOVIL - Notificación de transacción realizada" (`mensajero@bancobcr.com`), pero en 60 días hubo uno solo; los SINPE por SMS no generan correo. También existen correos de ingresos "Pagos Inmediatos - Notificación…" y "Débito en Tiempo Real Entrante…" (`BCRNotificacion@bancobcr.com`), pocos; posible mejora futura, no pedida.
- **Compilar Android** requiere `dl.google.com` (SDK y también `maven.google.com`, que redirige ahí). Las pruebas de `Sms4066.kt` se pueden correr en la JVM sin el SDK.
- **Categorías base** (migración 0002): Comida, Supermercado, Transporte, Servicios, Suscripciones, Salud, Entretenimiento, Otros.

## Comandos

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                                  # todos los tests
.venv/bin/finanzas configurar-gmail TU@gmail.com  # pide la contraseña de aplicación
.venv/bin/finanzas importar [--desde 2026-01-01]
.venv/bin/finanzas reprocesar [--fuente gmail_bcr]
.venv/bin/finanzas ui                             # UI en http://127.0.0.1:8765
scripts/instalar_systemd.sh                       # timer cada 5 min + servicio de la UI
scripts/abrir_ui.sh                               # ventana de app (atajo de Hyprland)
systemctl --user restart finanzas-ui              # tras actualizar el código
journalctl --user -u finanzas-importar.service    # logs del importador
```

Requiere Python 3.12+. Dependencias de runtime: fastapi, uvicorn, jinja2, python-multipart (solo para la UI). Dev: pytest, httpx (los tests web se saltan si falta fastapi). Paquetes del sistema: `libsecret` (`secret-tool`), un proveedor de Secret Service desbloqueado (gnome-keyring), `libnotify` (`notify-send`) y, para la ventana propia, `python-gobject` + `webkitgtk-6.0`.

## Estado de etapas

- [x] **Etapa 0: Base.** Esquema + migraciones, parsers BCR y SINPE con fixtures, ingesta idempotente y reproceso.
- [x] **Etapa 1: Importador de Gmail.** IMAP solo lectura, llavero, systemd, CLI. 47 tests con IMAP simulado. Aceptada en la PC (26-oct-2026): backfill de 180 días = 561 correos → 466 transacciones aprobadas (425 CRC, 41 USD), 95 correos `Negada`, 0 duplicados, 0 errores; el timer corre cada 5 min.
- [x] **Etapa 2: UI de escritorio.** Dashboard, transacciones, bandeja con reglas, ingresos manuales y recurrentes, reglas, cuentas y categorías, tipo de cambio; servicio de usuario y atajo. 75 tests (incluye la aceptación vía UI). Aceptada en la PC (26-oct-2026): categorizar un pendiente crea la regla y las iguales quedan categorizadas. Confirmado por el usuario: "extraordinario" como casilla y USD aparte salvo que haya tipo de cambio.
- [~] **Etapa 3: App Android.** Código completo en `android/`; lógica pura probada en la JVM (5 pruebas) y su JSON verificado con el parser de la PC. Falta compilar (bloqueado: `dl.google.com` no está permitido en el entorno), decidir dónde vive la llave de firma y la aceptación en el Fold.
- [ ] Etapa 4: Importador de eventos del teléfono.
- [ ] Etapa 5: Pulido.

## Correo BCR real (verificado oct-2026)

- Remitente `bcrtarjestcta@bancobcr.com`, asunto `Notificación de Transacciones BCR`. El mismo remitente manda otros correos (p. ej. "Ahora puede usar Google Pay"): por eso se filtra también por asunto.
- Estructura: encabezado de tarjeta en un `div`, tabla con `thead`/`tbody` y `th`. Normalmente una fila por correo. El pie trae un enlace de WhatsApp que repite los datos en la URL (solo atributo, el parser lo ignora). Réplica sanitizada en `tests/fixtures/bcr/una_fila.html`.
- Montos con coma de miles (`1,614.72`). Hay dos tarjetas en uso (dos cuentas distintas).
- Estados vistos: `Aprobada` y `Negada` (~17% de los correos). Las negadas quedan solo en `raw_events` (`con_avisos`).
- Algunos comercios de Uber llegan como `UBR PENDING ...` (posible preautorización); revisar en la Etapa 2 si después llega el cargo final.
