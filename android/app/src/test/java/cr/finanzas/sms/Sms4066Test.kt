package cr.finanzas.sms

import java.time.Instant
import java.time.ZoneId
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Sms4066Test {

    // Mismo texto ficticio que tests/fixtures/sms/almuerzo.json en la PC.
    private val cuerpo = "Ha enviado 2,500.00 Colones a NOMBRE APELLIDO APELLIDO por SINPE Movil, " +
        "Almuerzo*********. Comprobante 2026102215283000000000001."
    private val costaRica = ZoneId.of("America/Costa_Rica")
    private val recibidoMs = Instant.parse("2026-10-22T21:28:41.789Z").toEpochMilli()

    @Test
    fun soloElRemitente4066() {
        assertTrue(Sms4066.esDelRemitente("4066"))
        assertTrue(Sms4066.esDelRemitente(" 4066 "))
        assertFalse(Sms4066.esDelRemitente("+50688884066"))
        assertFalse(Sms4066.esDelRemitente("40661"))
        assertFalse(Sms4066.esDelRemitente(null))
    }

    @Test
    fun extraeElComprobante() {
        assertEquals("2026102215283000000000001", Sms4066.comprobante(cuerpo))
        assertNull(Sms4066.comprobante("Su código de verificación es 123456"))
    }

    @Test
    fun sinComprobanteNoHayEvento() {
        assertNull(Sms4066.evento("Saldo insuficiente", recibidoMs, costaRica))
    }

    @Test
    fun fechaIsoConOffsetAlSegundo() {
        assertEquals("2026-10-22T15:28:41-06:00", Sms4066.fechaIso(recibidoMs, costaRica))
    }

    @Test
    fun jsonConElEsquemaAcordado() {
        val evento = Sms4066.evento(cuerpo, recibidoMs, costaRica)!!
        assertEquals("2026102215283000000000001.json", evento.nombreArchivo)
        val json = JSONObject(evento.aJson())
        assertEquals(6, json.length())
        assertEquals(1, json.getInt("schema_version"))
        assertEquals("2026102215283000000000001", json.getString("event_id"))
        assertEquals("sms_4066", json.getString("source"))
        assertEquals("2026-10-22T15:28:41-06:00", json.getString("received_at"))
        assertEquals(cuerpo, json.getString("body"))
        assertEquals("fold8", json.getString("device"))
    }
}
