package cr.finanzas.sms

import android.content.Context
import android.provider.Telephony
import java.time.ZoneId

/**
 * Exporta los SMS antiguos del 4066 que están en la bandeja de entrada.
 * Solo consulta la bandeja de entrada (nunca los enviados) y solo la dirección 4066.
 */
object Backfill {

    data class Resultado(val nuevos: Int, val yaExportados: Int, val sinComprobante: Int, val enCola: Int)

    fun ejecutar(contexto: Context): Resultado {
        var nuevos = 0
        var yaExportados = 0
        var sinComprobante = 0
        var enCola = 0
        val cola = Cola.de(contexto)
        val existentes = Entrega.nombresEnCarpeta(contexto)
        val zona = ZoneId.systemDefault()
        val cursor = contexto.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.BODY, Telephony.Sms.DATE),
            "${Telephony.Sms.ADDRESS} = ?",
            arrayOf(Sms4066.REMITENTE),
            "${Telephony.Sms.DATE} ASC",
        )
        if (cursor == null) {
            return Resultado(0, 0, 0, 0)
        }
        cursor.use {
            while (it.moveToNext()) {
                val cuerpo = it.getString(0)
                if (cuerpo == null) {
                    sinComprobante += 1
                    continue
                }
                val evento = Sms4066.evento(cuerpo, it.getLong(1), zona)
                if (evento == null) {
                    sinComprobante += 1
                } else if (cola.yaExportado(evento.eventId)) {
                    yaExportados += 1
                } else if (Entrega.entregar(contexto, evento, existentes)) {
                    nuevos += 1
                } else {
                    enCola += 1
                }
            }
        }
        return Resultado(nuevos, yaExportados, sinComprobante, enCola)
    }
}
