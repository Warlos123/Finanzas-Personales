package cr.finanzas.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import java.time.ZoneId

/**
 * SMS entrantes. Solo procesa los del 4066 con comprobante; el resto se ignora sin leer más.
 * Un SMS largo llega en varias partes: se unen en orden.
 */
class ReceptorSms : BroadcastReceiver() {

    override fun onReceive(contexto: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) {
            return
        }
        val partes = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (partes == null || partes.isEmpty() || !Sms4066.esDelRemitente(partes[0].originatingAddress)) {
            return
        }
        val cuerpo = StringBuilder()
        for (i in partes.indices) {
            val texto = partes[i].messageBody
            if (texto != null) {
                cuerpo.append(texto)
            }
        }
        val evento = Sms4066.evento(cuerpo.toString(), System.currentTimeMillis(), ZoneId.systemDefault())
        if (evento == null) {
            return
        }
        val aplicacion = contexto.applicationContext
        val pendiente = goAsync()
        Thread {
            try {
                Entrega.entregar(aplicacion, evento)
            } finally {
                pendiente.finish()
            }
        }.start()
    }
}
