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
- Red: solo IMAP a Gmail y el GET diario del tipo de cambio a Hacienda (pedido por el usuario). Nada más sale de la PC.

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
  telefono.py          importa los JSON del teléfono (carpeta Syncthing) → procesados/ o rechazados/
  alertas.py           estado de sincronización y notificaciones (novedades, teléfono, presupuestos, gasto atípico)
  respaldos.py         backup diario con la API de SQLite, rotación de 14
  resumen.py           resumen mensual en Markdown + notificación
  suscripciones.py     detección de cobros mensuales recurrentes
  graficos.py          datos y geometría SVG de la página de gráficos
  tipo_cambio.py       tipo de cambio diario (venta de referencia del BCCR) desde la API de Hacienda
  estado_cuenta.py     lee el PDF del estado de cuenta BCR (`pdftotext -layout`) y valida los totales
  reconciliacion.py    compara el estado con la app (coinciden / faltan / solo en la app) y agrega lo elegido
  ahorros.py           ahorros e inversiones (CDP, S&P 500) con valores a mano y totales en colones
  cli.py, __main__.py  comando `finanzas` (configurar-gmail, configurar-telefono, importar, reprocesar, ui)
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
- **Caché del CSS**: `base.html` enlaza `estilo.css?v=<hash del contenido>` (WebKitGTK guardaba el CSS viejo y el gráfico salía negro). El SVG de gráficos lleva atributos de respaldo (`fill`, `font-size`) por si el CSS no carga.
- **UI**: FastAPI + Jinja2 con formularios HTML y POST→redirect (sin HTMX ni JS de terceros; solo `onchange` y `confirm()` inline: el de la regla en la bandeja y "marcar todos" en la reconciliación). Puerto 8765, siempre `127.0.0.1`. Middleware: Host debe ser `127.0.0.1:8765`/`localhost:8765` y los POST deben traer Origin local (evita DNS rebinding y CSRF desde otras pestañas). `?volver=` solo acepta rutas internas.
- **Reglas**: patrón "contiene", sin tildes ni mayúsculas. `comercio` aplica a cuentas no SINPE, `destinatario` a SINPE, `descripcion` a la descripción. Orden por `prioridad` ascendente; gana la primera. Solo tocan transacciones sin categoría, sin `editada_en` y no ignoradas. Se aplican al importar (nuevas) y al crear/editar reglas (todas las candidatas).
- **Bandeja**: gastos sin categoría + transacciones `pendiente` (no ignoradas), una fila por comercio/destinatario con el conteo de iguales. Las `Negada` quedan fuera (no son transacciones). Es **un solo formulario** (`POST /bandeja`, campos `<campo>_<id>` + `id` repetido): se eligen categorías en varias filas y se guarda una vez (antes, cada fila recargaba la página y se perdían las demás elecciones). Filas sin decisión no cambian; "Ignorar" es casilla. Primero se aplican las elecciones a mano y después las reglas nuevas, así lo elegido gana. Categorizar desde la bandeja no marca `editada_en`; la edición completa sí (y entonces el reproceso no la pisa).
- **Ingresos manuales**: transacción `ingreso` sin llave; la fuente va en `comercio_o_destinatario`; `extraordinario` = 1 para bonos/aguinaldo. Solo las manuales se borran; las importadas se ignoran.
- **Recurrentes**: llave `recurrente:<id>:<AAAA-MM>`, desde `recurring_incomes.desde`; día 31 → último día del mes. Se generan al abrir el dashboard o Ingresos. "Borrar" uno generado lo deja ignorado (si no, se regeneraría).
- **Métricas**: todo en CRC. USD se convierte con `settings.tipo_cambio_usd` si existe; si no, se muestra aparte. Transferencias y reembolsables aparte. La comparación con el mes anterior usa la proyección en el mes en curso.
- **Android**: Kotlin sin AppCompat ni Compose (Activity del framework + XML); dependencias: documentfile y work-runtime. minSdk 31, targetSdk 35. Sin permiso INTERNET. Solo exporta SMS entrantes del 4066 que traen `Comprobante <dígitos>`; los demás se descartan sin guardarse. `received_at` = hora de llegada al teléfono (en vivo `currentTimeMillis`, en backfill la columna `date` de la bandeja). Intenta escribir directo y, si falla, cola + WorkManager (`vaciar-cola`, KEEP, backoff 30 s). La tabla `exportados` evita archivos duplicados aunque la PC mueva los JSON. Firma desde `android/firma.properties` (fuera de git). **Llave solo en la PC del usuario** (decisión, opción 2): en la primera compilación se genera `android/finanzas.keystore` con contraseña aleatoria y se le entregan el keystore y `firma.properties`; él los guarda en `~/Finanzas-Personales/android/` (ignorados por git). Para compilar actualizaciones en otra sesión, pedirle que adjunte ambos archivos; nunca commitearlos.
- **Se mantiene el teléfono** (decisión del usuario, 27-oct-2026): se evaluó capturar los SINPE solo por correo. El BCR sí manda "SINPEMOVIL - Notificación de transacción realizada" (`mensajero@bancobcr.com`), pero en 60 días hubo uno solo; los SINPE por SMS no generan correo. También existen correos de ingresos "Pagos Inmediatos - Notificación…" y "Débito en Tiempo Real Entrante…" (`BCRNotificacion@bancobcr.com`), pocos; posible mejora futura, no pedida.
- **Compilar Android** requiere `dl.google.com` (SDK y también `maven.google.com`, que redirige ahí); el entorno ya lo permite (red **Custom** con `dl.google.com` + lista por defecto). Versiones: AGP 8.11.1, Kotlin 2.2.0, Gradle 8.14.3, compile/target SDK 35. En una sesión nueva: bajar `commandlinetools-linux-*_latest.zip` a `/root/android-sdk/cmdline-tools/latest`, `yes | sdkmanager --licenses`, `sdkmanager "platforms;android-35" "build-tools;35.0.0"`, `echo sdk.dir=/root/android-sdk > android/local.properties`, pedir al usuario `finanzas.keystore` + `firma.properties` y `gradle -p android --max-workers=2 testDebugUnitTest assembleRelease` (`--max-workers=2` evita el 429 de Maven Central). Subir `versionCode` en cada APK nuevo.
- **Eventos del teléfono (PC)**: carpeta en `settings.telefono_carpeta` (`finanzas configurar-telefono RUTA`); en la PC del usuario está dentro del repo (`~/Finanzas-Personales/finanzas-eventos`, ignorada por git). Lee solo `*.json` de la raíz (ignora `.…` y `~…`, temporales de Syncthing). Valida esquema v1 (`source` = `sms_4066`, `event_id` numérico, `received_at` con offset, `body`); lo inválido va a `rechazados/` sin importarse. Lo válido pasa por `ingesta.importar_evento` y se mueve a `procesados/` (también los duplicados). `configurar-telefono` agrega `procesados` y `rechazados` al `.stignore`: al moverlos, el teléfono los borra de su carpeta. `import_runs` de `sms_4066` solo se registra si hubo archivos.
- **`importar`** corre teléfono y Gmail de forma independiente (si uno falla, el otro sigue) y después las alertas. Código de salida: el de Gmail si falló; si no, 4 cuando la carpeta del teléfono no existe; si no, 0.
- **Alertas**: (1) una notificación por corrida si subió la bandeja o los eventos con error; (2) teléfono atrasado si pasan **3 días** sin eventos nuevos (`settings.telefono_ultimo_evento` = `received_at` más reciente; si nunca llegó uno, desde `telefono_configurado_en`), una sola vez por cada último evento (`settings.aviso_telefono_para`). Limitación conocida: 3 días sin hacer SINPE también dispara el aviso. Presupuestos y gasto atípico: Etapa 5.
- **Tareas después de `importar`** (cada 5 min con el timer), cada una aislada (si falla, se loguea el tipo de error y siguen las demás): tipo de cambio, aviso de novedades, teléfono atrasado, presupuestos, gasto atípico, backup diario y resumen mensual.
- **Backups**: `backups/finanzas-AAAA-MM-DD.db` junto a la base (carpeta 0700), uno por día con `conn.backup()` a un temporal + rename; se conservan 14.
- **Exportar CSV**: `GET /transacciones.csv` con los mismos filtros de la lista; columnas fijas, monto decimal con punto, BOM UTF-8. En la ventana WebKitGTK se guarda en Descargas.
- **Presupuestos**: por categoría en `budgets` (CRC), se editan en "Cuentas y categorías" (vacío = sin presupuesto). El gasto de una categoría suma el de sus subcategorías directas. Avisos al 80% y al 100%, uno por categoría/umbral/mes (`settings.aviso_presupuesto:<mes>:<cat>:<umbral>`).
- **Gasto atípico**: gasto creado en la corrida > ₡20,000 y > 3× la mediana de su categoría (o de todos los gastos si no tiene categoría) en los 90 días previos, con al menos 5 de referencia. Un aviso por corrida; en SINPE no se muestra el destinatario.
- **Suscripciones**: cobros con tarjeta (no SINPE) al mismo comercio y moneda, ≥3 en ≥3 meses dentro de 400 días, intervalo mediano 25–35 días, monto máx ≤ 1.25 × mín, último cobro hace ≤ 45 días. Se muestran en el dashboard y en el resumen.
- **Resumen mensual**: el primer `importar` de cada mes escribe `resumenes/AAAA-MM.md` (junto a la base) del mes anterior si hubo transacciones, y notifica gasto, ingresos y ahorro. No se regenera si el archivo existe.
- **Gráficos** (pedido por el usuario): página `/graficos?mes=` con (1) columnas de gasto de los últimos 12 meses (SVG del servidor, una serie: el mes elegido en `--acento` con su valor, el resto en `--barra-tenue`; gris claro `#8d9590` y oscuro `#6e757b` validados con el script de la skill dataviz: contraste ≥ 3:1 y ΔE ≥ 14 contra el acento; tooltip nativo `<title>` y tabla en `<details>`) y (2) los 10 gastos individuales más grandes del mes (barras HTML). Cada columna es un enlace `?mes=…&detalle=AAAA-MM#grandes`: muestra abajo los más grandes de ese mes y lo resalta (`detalle` fuera de los 12 meses o inválido → el mes del gráfico). USD solo entran con tipo de cambio.
- **Tipo de cambio automático** (pedido por el usuario, 27-oct-2026; eligió Hacienda y venta): `GET https://api.hacienda.go.cr/indicadores/tc/dolar` (pública, sin registro ni datos del usuario; respuesta esperada `{"venta": {"fecha", "valor"}, "compra": {...}}`), `venta.valor` redondeado a 2 decimales en `settings.tipo_cambio_usd`. Una vez al día como tarea de `importar`; `settings.tipo_cambio_actualizado` guarda la hora de la consulta. Si falla (red o formato), no guarda nada y reintenta en la siguiente corrida. El valor puesto a mano dura hasta la actualización del día siguiente. Un solo valor para todos los meses (no hay histórico por fecha). Solo `urllib` (sin dependencias). Las pruebas bloquean `urllib.request.urlopen` (conftest). Verificado en la PC por el usuario (27-oct-2026). Desde la nube el host está bloqueado: las pruebas usan un fixture.
- **Reconciliación** (propuesta aceptada por el usuario, 28-oct-2026; no tiene tarjeta de crédito, solo la cuenta de ahorros con tarjeta de débito): página `/reconciliar` para subir el PDF (máx. 10 MB). Se guarda en `bank_statements` solo el texto de `pdftotext` (UNIQUE por hash), no el PDF. Débito/crédito por posición de columna (punto medio entre los encabezados de la página) y se rechaza si no cuadra con los totales y el saldo final. Emparejamiento: compras por (últimos 4, autorización = Documento); el resto por monto, moneda, dirección (débito ↔ gasto/transferencia/reembolsable, crédito ↔ ingreso/transferencia/reembolsable) y ≤ 3 días, la más cercana. Internos (`EMISION CDP`, `CANC CDP`, `TRAN CTA AH TAR VIRT`) aparte y sin proponer. "Solo en la app": del período, de las tarjetas del estado, SINPE y lo agregado desde estados. Se agrega con casilla + tipo en un solo formulario (créditos sugeridos como ingreso, débitos como gasto; "ignorar" crea la transacción ignorada para que no reaparezca). Llave `estado:<AAAA-MM-DD>:<documento>:<céntimos>`, hora 00:00; cuentas: la tarjeta por últimos 4, `SINPE Móvil` o `Cuenta de ahorros BCR` (tipo otra). En SINPE el texto queda en `descripcion` sin el teléfono ni el relleno; en el resto, el detalle en `comercio_o_destinatario` y el tipo de movimiento en `descripcion`. Probado con el PDF real (163 movimientos, cuadra); el fixture es ficticio con el mismo acomodo de columnas.
- **Animaciones** (pedido del usuario, 28-oct-2026): solo CSS en `estilo.css`. Al entrar a cada pestaña el `main` se desliza; tarjetas, filas y pendientes aparecen en cascada (`--i` por `:nth-of-type`, máx. 12 pasos); barras crecen desde la izquierda y columnas del gráfico desde la base; transiciones en pestañas, botones y tarjetas. `animation-fill-mode: backwards` (al terminar no queda nada fijado). `prefers-reduced-motion: reduce` las apaga todas.
- **Ahorros** (pedido del usuario, 28-oct-2026, "sencillo, después agregamos más"): pestaña `/ahorros` con tabla `savings` (tipo `cdp`|`sp500` validado en Python para sumar tipos sin migrar; nombre, moneda, invertido, valor actual —vacío = lo invertido—, tasa anual % y vencimiento solo CDP, inicio, notas, `actualizado_en`). Todo a mano: no se consultan precios (la red sigue limitada a Gmail y Hacienda). Totales en colones con el tipo de cambio; USD sin tipo de cambio aparte. CDP que vencen en ≤ 30 días se marcan. Edición en `/ahorros/{id}`.
- **Categorías base** (migración 0002): Comida, Supermercado, Transporte, Servicios, Suscripciones, Salud, Entretenimiento, Otros.

## Comandos

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                                  # todos los tests
.venv/bin/finanzas configurar-gmail TU@gmail.com  # pide la contraseña de aplicación
.venv/bin/finanzas configurar-telefono ~/Finanzas-Personales/finanzas-eventos
.venv/bin/finanzas importar [--desde 2026-01-01]       # teléfono + Gmail + alertas
.venv/bin/finanzas reprocesar [--fuente gmail_bcr]
.venv/bin/finanzas ui                             # UI en http://127.0.0.1:8765
scripts/instalar_systemd.sh                       # timer cada 5 min + servicio de la UI
scripts/abrir_ui.sh                               # ventana de app (atajo de Hyprland)
systemctl --user restart finanzas-ui              # tras actualizar el código
journalctl --user -u finanzas-importar.service    # logs del importador
```

Requiere Python 3.12+. Dependencias de runtime: fastapi, uvicorn, jinja2, python-multipart (solo para la UI). Dev: pytest, httpx (los tests web se saltan si falta fastapi). Paquetes del sistema: `poppler` (`pdftotext`, para la reconciliación), `libsecret` (`secret-tool`), un proveedor de Secret Service desbloqueado (gnome-keyring), `libnotify` (`notify-send`) y, para la ventana propia, `python-gobject` + `webkitgtk-6.0`.

## Estado de etapas

- [x] **Etapa 0: Base.** Esquema + migraciones, parsers BCR y SINPE con fixtures, ingesta idempotente y reproceso.
- [x] **Etapa 1: Importador de Gmail.** IMAP solo lectura, llavero, systemd, CLI. 47 tests con IMAP simulado. Aceptada en la PC (26-oct-2026): backfill de 180 días = 561 correos → 466 transacciones aprobadas (425 CRC, 41 USD), 95 correos `Negada`, 0 duplicados, 0 errores; el timer corre cada 5 min.
- [x] **Etapa 2: UI de escritorio.** Dashboard, transacciones, bandeja con reglas, ingresos manuales y recurrentes, reglas, cuentas y categorías, tipo de cambio; servicio de usuario y atajo. 75 tests (incluye la aceptación vía UI). Aceptada en la PC (26-oct-2026): categorizar un pendiente crea la regla y las iguales quedan categorizadas. Confirmado por el usuario: "extraordinario" como casilla y USD aparte salvo que haya tipo de cambio.
- [x] **Etapa 3: App Android.** Aceptada en el Fold (27-oct-2026): los SMS del 4066 generan su JSON en `Documents/finanzas-eventos`. Compilada: APK 0.1.0 (versionCode 1) firmado v2 con la llave del usuario (SHA-256 del certificado `ccc1219e…b58ed`), 5 pruebas JVM, lint sin errores, sin permiso INTERNET. Entregados al usuario el APK, `finanzas.keystore` y `firma.properties`.
- [x] **Etapa 4: Importador de eventos del teléfono.** Importación de la carpeta, procesados/rechazados, `.stignore`, estado de sincronización en el dashboard y alertas. 88 tests. Aceptada en la PC (27-oct-2026): Syncthing emparejado (Fold ↔ `~/Finanzas-Personales/finanzas-eventos`), los SINPE llegan a la base y salió la notificación de transacciones nuevas.
- [~] **Etapa 5: Pulido.** Hecho: backups diarios, exportar CSV, presupuestos con avisos, gasto atípico, suscripciones, resumen mensual, gráficos (pedido extra; clic en una columna → gastos más grandes de ese mes), tipo de cambio diario desde Hacienda (pedido extra) reconciliación con el estado de cuenta en PDF, animaciones y pestaña de Ahorros (pedidos extra). 133 tests. Falta: probar la reconciliación con un mes reciente (septiembre) en la PC y la revisión del usuario.

## Correo BCR real (verificado oct-2026)

- Remitente `bcrtarjestcta@bancobcr.com`, asunto `Notificación de Transacciones BCR`. El mismo remitente manda otros correos (p. ej. "Ahora puede usar Google Pay"): por eso se filtra también por asunto.
- Estructura: encabezado de tarjeta en un `div`, tabla con `thead`/`tbody` y `th`. Normalmente una fila por correo. El pie trae un enlace de WhatsApp que repite los datos en la URL (solo atributo, el parser lo ignora). Réplica sanitizada en `tests/fixtures/bcr/una_fila.html`.
- Montos con coma de miles (`1,614.72`). Hay dos tarjetas en uso (dos cuentas distintas).
- Estados vistos: `Aprobada` y `Negada` (~17% de los correos). Las negadas quedan solo en `raw_events` (`con_avisos`).
- Algunos comercios de Uber llegan como `UBR PENDING ...`: es el cargo final, no una preautorización aparte (en el estado de cuenta aparece una sola vez como `UBER *TRIP`, misma autorización y monto).

## Estado de cuenta BCR (PDF, visto oct-2026)

- El BCR solo lo deja descargar en PDF (Microsoft Reporting Services). Muestra: cuenta de ahorros en colones, período del 1 al 30 del mes; trae las compras de la tarjeta de débito (columna Tarjeta = últimos 4), SINPE y transferencias.
- Columnas: Fecha Movimiento (`dd/mm/aa`), Fecha Contable, Tarjeta, Documento, Concepto (`TIPO - detalle`), Monto Débito, Monto Crédito. Débito o crédito **solo se distingue por la posición** de la columna. El encabezado se repite en cada página; arriba vienen el saldo anterior y el período de corte, y al final los totales de débitos y créditos y el saldo final (sirven para validar la lectura). Entran compras de días previos si su fecha contable cae en el período.
- **Documento de una compra = Autorización del correo sin ceros a la izquierda** (verificado con 2 compras).
- Tipos vistos: `COMPRAS EN COMERCIOS`; `MONEDERO SINPE MOVIL` y `SINPE MOVIL OTRA ENT` (débito = enviado, crédito = recibido); `TRANSFERENC BANCOBCR` (en ambos sentidos); `TRAN CTA AH TAR VIRT`; `EMISION CDP` / `CANC CDP` (movimientos internos); `CUPONES CDPS ELECTR` e `INTS GANADOS` (intereses); `SERV ADMIN VISA AH` (comisión).
- El detalle de los SINPE puede traer un número de teléfono: nunca loguearlo; en los fixtures, número ficticio.
- Hay compras con tarjeta que no generaron correo (p. ej. parqueos); la reconciliación es la forma de detectarlas.
