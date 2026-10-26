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

## Comandos

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest            # todos los tests
```

Requiere Python 3.12+. Sin dependencias de runtime por ahora.

## Estado de etapas

- [x] **Etapa 0: Base.** Esquema + migraciones, parsers BCR y SINPE con fixtures, ingesta idempotente y reproceso. 27 tests.
- [ ] Etapa 1: Importador de Gmail (IMAP, keyring, systemd, CLI de reproceso).
- [ ] Etapa 2: UI de escritorio.
- [ ] Etapa 3: App Android.
- [ ] Etapa 4: Importador de eventos del teléfono.
- [ ] Etapa 5: Pulido.

## Correo BCR real (verificado oct-2026)

- Remitente `bcrtarjestcta@bancobcr.com`, asunto `Notificación de Transacciones BCR`. El mismo remitente manda otros correos (p. ej. "Ahora puede usar Google Pay"): en la Etapa 1 filtrar también por asunto.
- Estructura: encabezado de tarjeta en un `div`, tabla con `thead`/`tbody` y `th`. Normalmente una fila por correo. El pie trae un enlace de WhatsApp que repite los datos en la URL (solo atributo, el parser lo ignora). Réplica sanitizada en `tests/fixtures/bcr/una_fila.html`.
- Montos con coma de miles (`1,614.72`). Hay dos tarjetas en uso (dos cuentas distintas).
- Algunos comercios de Uber llegan como `UBR PENDING ...` (posible preautorización); revisar en la Etapa 2 si después llega el cargo final.
