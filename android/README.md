# Finanzas SMS (Android)

App mínima para el Fold: captura los SMS de SINPE Móvil del **4066** y escribe un archivo
`<comprobante>.json` por evento en la carpeta sincronizada con Syncthing. No tiene UI de gastos:
eso está en la PC.

## Qué hace

- Al llegar un SMS del 4066 con "Comprobante …", escribe el JSON en la carpeta elegida.
- Si no puede escribir (carpeta sin permiso, almacenamiento ocupado), lo guarda en una cola local
  y WorkManager reintenta con espera creciente.
- **Backfill de SMS antiguos**: exporta los SMS del 4066 que ya están en la bandeja de entrada.
- Nunca escribe dos veces el mismo comprobante (lleva registro local de los exportados).

Esquema del JSON (`schema_version` 1):

```json
{ "schema_version": 1, "event_id": "<comprobante>", "source": "sms_4066",
  "received_at": "2026-10-22T15:28:41-06:00", "body": "<texto del SMS>", "device": "fold8" }
```

## Privacidad

- Solo SMS **entrantes** del 4066 que traen comprobante. Nunca lee los enviados (los "Pase …" con
  números de teléfono) ni SMS de otros remitentes.
- La app no tiene permiso de Internet: no puede enviar nada a ningún lado. Lo único que sale del
  teléfono es lo que Syncthing sincroniza con tu PC.
- Los logs no incluyen el texto de los SMS ni nombres. Sin respaldo en la nube (`allowBackup=false`).

## Instalar en el Fold (sideload)

1. Copia el APK al teléfono (por Syncthing o por cable) y ábrelo desde Mis archivos. Si lo pide,
   permite "Instalar apps desconocidas" para Mis archivos.
2. Abre **Finanzas SMS** y toca **Conceder permisos**. Por ser una app instalada fuera de la
   tienda, Android bloquea los permisos de SMS ("Configuración restringida"):
   - Ajustes → Aplicaciones → Finanzas SMS → menú **⋮** (arriba a la derecha) →
     **Permitir ajustes restringidos** (pide huella o PIN).
   - Vuelve a la app → **Conceder permisos** → Permitir.
3. **Elegir carpeta** → la carpeta compartida con Syncthing (p. ej. `Documents/finanzas-eventos`)
   → Usar esta carpeta → Permitir.
4. **Quitar optimización de batería** → Permitir. En Samsung, además: Ajustes → Batería →
   Límites de uso en segundo plano → **Aplicaciones que nunca entran en suspensión** → agrega
   Finanzas SMS. Sin esto Android puede atrasar o bloquear la captura.
5. Opcional: **Backfill de SMS antiguos**.

Para actualizar, instala el APK nuevo encima (tiene que estar firmado con la misma llave).

## Compilar

Requiere el SDK de Android (`ANDROID_HOME`, o `sdk.dir=…` en `android/local.properties`) y JDK 17+.

```bash
cd android
./gradlew test             # pruebas de la lógica (remitente, comprobante, fecha, JSON)
./gradlew assembleRelease  # app/build/outputs/apk/release/app-release.apk
```

La firma se lee de `android/firma.properties` (fuera de git):

```properties
storeFile=finanzas.keystore
storePassword=…
keyAlias=finanzas
keyPassword=…
```
