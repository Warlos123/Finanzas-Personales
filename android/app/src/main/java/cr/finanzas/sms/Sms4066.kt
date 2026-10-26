package cr.finanzas.sms

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import org.json.JSONObject

/**
 * Reglas del SMS de SINPE Móvil del 4066. Sin dependencias de Android para probarlas en la JVM.
 *
 * Solo se exportan SMS entrantes del 4066 que traen "Comprobante <número>": el comprobante es el
 * event_id. Cualquier otro SMS (incluidos los que yo envío, con números de teléfono) se descarta
 * sin guardarlo.
 */
object Sms4066 {
    const val REMITENTE = "4066"
    const val DISPOSITIVO = "fold8"
    private val PATRON_COMPROBANTE = Regex("""Comprobante\s+(\d{10,})""")

    /** Compara solo los dígitos de la dirección: "4066" sí; "+506 4066 1234" no. */
    fun esDelRemitente(direccion: String?): Boolean {
        if (direccion == null) {
            return false
        }
        val digitos = StringBuilder()
        for (i in direccion.indices) {
            if (direccion[i].isDigit()) {
                digitos.append(direccion[i])
            }
        }
        return digitos.toString() == REMITENTE
    }

    fun comprobante(cuerpo: String): String? {
        val coincidencia = PATRON_COMPROBANTE.find(cuerpo)
        if (coincidencia == null) {
            return null
        }
        return coincidencia.groupValues[1]
    }

    /** Evento listo para exportar, o null si el SMS no trae comprobante. */
    fun evento(cuerpo: String, recibidoMs: Long, zona: ZoneId): Evento? {
        val id = comprobante(cuerpo)
        if (id == null) {
            return null
        }
        return Evento(id, fechaIso(recibidoMs, zona), cuerpo)
    }

    /** ISO 8601 con offset, al segundo: 2026-10-22T15:28:41-06:00. */
    fun fechaIso(ms: Long, zona: ZoneId): String {
        val instante = Instant.ofEpochMilli(ms).truncatedTo(ChronoUnit.SECONDS)
        return instante.atZone(zona).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
    }
}

data class Evento(val eventId: String, val recibidoEn: String, val cuerpo: String) {
    val nombreArchivo: String
        get() = "$eventId.json"

    /** Esquema acordado con la PC (schema_version 1). */
    fun aJson(): String {
        val json = JSONObject()
        json.put("schema_version", 1)
        json.put("event_id", eventId)
        json.put("source", "sms_4066")
        json.put("received_at", recibidoEn)
        json.put("body", cuerpo)
        json.put("device", Sms4066.DISPOSITIVO)
        return json.toString(2)
    }
}
