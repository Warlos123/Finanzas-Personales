# CLAUDE.md

App personal de finanzas (un usuario, Costa Rica). Todo local: la PC importa correos BCR (IMAP) y SMS SINPE (JSON vía Syncthing desde Android) a SQLite. Ver el diseño completo en las instrucciones originales del proyecto (secciones 1–11).

## Reglas de trabajo

- Trabajar por etapas; al cerrar cada una: resumir, actualizar este archivo y esperar confirmación.
- Cambios mínimos, commits pequeños. No agregar funciones no pedidas.
- Estilo: **sin operador ternario** (`x if c else y`) y **bucles `for` indexados** (`for i in range(len(xs))`) en vez de iterar la colección o usar comprehensions.
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
  cli.py, __main__.py  comando `finanzas` (configurar-gmail, importar, reprocesar)
systemd/               finanzas-importar.service.in + .timer (cada 5 min)
scripts/instalar_systemd.sh  instala las unidades de usuario con la ruta del venv
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

## Comandos

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                                  # todos los tests
.venv/bin/finanzas configurar-gmail TU@gmail.com  # pide la contraseña de aplicación
.venv/bin/finanzas importar [--desde 2026-01-01]
.venv/bin/finanzas reprocesar [--fuente gmail_bcr]
scripts/instalar_systemd.sh                       # timer cada 5 min
journalctl --user -u finanzas-importar.service    # logs del importador
```

Requiere Python 3.12+. Sin dependencias de Python en runtime. Paquetes del sistema: `libsecret` (`secret-tool`), un proveedor de Secret Service desbloqueado (gnome-keyring) y `libnotify` (`notify-send`).

## Estado de etapas

- [x] **Etapa 0: Base.** Esquema + migraciones, parsers BCR y SINPE con fixtures, ingesta idempotente y reproceso.
- [~] **Etapa 1: Importador de Gmail.** Implementada (IMAP solo lectura, llavero, systemd, CLI). 47 tests con IMAP simulado. Falta la aceptación en la PC: compras reales de los últimos meses en la base sin duplicados.
- [ ] Etapa 2: UI de escritorio.
- [ ] Etapa 3: App Android.
- [ ] Etapa 4: Importador de eventos del teléfono.
- [ ] Etapa 5: Pulido.

## Correo BCR real (verificado oct-2026)

- Remitente `bcrtarjestcta@bancobcr.com`, asunto `Notificación de Transacciones BCR`. El mismo remitente manda otros correos (p. ej. "Ahora puede usar Google Pay"): por eso se filtra también por asunto.
- Estructura: encabezado de tarjeta en un `div`, tabla con `thead`/`tbody` y `th`. Normalmente una fila por correo. El pie trae un enlace de WhatsApp que repite los datos en la URL (solo atributo, el parser lo ignora). Réplica sanitizada en `tests/fixtures/bcr/una_fila.html`.
- Montos con coma de miles (`1,614.72`). Hay dos tarjetas en uso (dos cuentas distintas).
- Algunos comercios de Uber llegan como `UBR PENDING ...` (posible preautorización); revisar en la Etapa 2 si después llega el cargo final.
