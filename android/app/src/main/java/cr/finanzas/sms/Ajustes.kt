package cr.finanzas.sms

import android.content.Context
import android.net.Uri

/** Preferencias: carpeta elegida (SAF) y último evento escrito. */
object Ajustes {
    private const val ARCHIVO = "ajustes"
    private const val CARPETA = "carpeta_uri"
    private const val ULTIMO_ID = "ultimo_event_id"
    private const val ULTIMO_MS = "ultimo_ms"

    private fun preferencias(contexto: Context) =
        contexto.applicationContext.getSharedPreferences(ARCHIVO, Context.MODE_PRIVATE)

    fun carpeta(contexto: Context): Uri? {
        val texto = preferencias(contexto).getString(CARPETA, null)
        if (texto == null) {
            return null
        }
        return Uri.parse(texto)
    }

    fun guardarCarpeta(contexto: Context, uri: Uri) {
        preferencias(contexto).edit().putString(CARPETA, uri.toString()).apply()
    }

    fun guardarUltimo(contexto: Context, eventId: String) {
        preferencias(contexto).edit()
            .putString(ULTIMO_ID, eventId)
            .putLong(ULTIMO_MS, System.currentTimeMillis())
            .apply()
    }

    fun ultimoId(contexto: Context): String? = preferencias(contexto).getString(ULTIMO_ID, null)

    fun ultimoMs(contexto: Context): Long = preferencias(contexto).getLong(ULTIMO_MS, 0L)
}
