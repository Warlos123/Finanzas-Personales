package cr.finanzas.sms

import android.content.Context
import android.util.Log
import androidx.documentfile.provider.DocumentFile
import java.io.IOException

/**
 * Escribe `<comprobante>.json` en la carpeta sincronizada con Syncthing (elegida con SAF).
 * Si no se puede, el evento queda en la cola local y WorkManager reintenta.
 * Los logs nunca incluyen el cuerpo del SMS ni nombres: solo conteos y el tipo de error.
 */
object Entrega {
    private const val TAG = "FinanzasSms"
    private const val TIPO = "application/json"

    fun carpeta(contexto: Context): DocumentFile? {
        val uri = Ajustes.carpeta(contexto)
        if (uri == null) {
            return null
        }
        val carpeta = DocumentFile.fromTreeUri(contexto, uri)
        if (carpeta == null || !carpeta.canWrite()) {
            return null
        }
        return carpeta
    }

    /** Nombres de archivo ya presentes; listar una vez evita recorrer la carpeta por cada evento. */
    fun nombresEnCarpeta(contexto: Context): MutableSet<String> {
        val nombres = HashSet<String>()
        val carpeta = carpeta(contexto)
        if (carpeta == null) {
            return nombres
        }
        val archivos = carpeta.listFiles()
        for (i in archivos.indices) {
            val nombre = archivos[i].name
            if (nombre != null) {
                nombres.add(nombre)
            }
        }
        return nombres
    }

    /** true si quedó escrito (o ya lo estaba); false si quedó en la cola para reintentar. */
    fun entregar(contexto: Context, evento: Evento, existentes: MutableSet<String>? = null): Boolean {
        val cola = Cola.de(contexto)
        if (cola.yaExportado(evento.eventId)) {
            return true
        }
        try {
            escribir(contexto, evento, existentes)
            cola.marcarExportado(evento.eventId)
            Ajustes.guardarUltimo(contexto, evento.eventId)
            return true
        } catch (error: Exception) {
            cola.encolar(evento)
            TrabajoReintento.programar(contexto)
            Log.w(TAG, "Evento en cola para reintentar (${error.javaClass.simpleName})")
            return false
        }
    }

    /** Intenta escribir todo lo pendiente. true si la cola quedó vacía. */
    fun vaciarCola(contexto: Context): Boolean {
        val cola = Cola.de(contexto)
        val pendientes = cola.pendientes()
        if (pendientes.isEmpty()) {
            return true
        }
        val existentes = nombresEnCarpeta(contexto)
        var fallidos = 0
        for (i in pendientes.indices) {
            try {
                escribir(contexto, pendientes[i], existentes)
                cola.marcarExportado(pendientes[i].eventId)
                Ajustes.guardarUltimo(contexto, pendientes[i].eventId)
            } catch (error: Exception) {
                fallidos += 1
            }
        }
        Log.i(TAG, "Cola: ${pendientes.size - fallidos} escritos, $fallidos pendientes")
        return fallidos == 0
    }

    private fun escribir(contexto: Context, evento: Evento, existentes: MutableSet<String>?) {
        val carpeta = carpeta(contexto)
        if (carpeta == null) {
            throw IOException("Sin carpeta elegida o sin permiso de escritura")
        }
        val nombre = evento.nombreArchivo
        var yaExiste = false
        if (existentes != null) {
            yaExiste = existentes.contains(nombre)
        } else if (carpeta.findFile(nombre) != null) {
            yaExiste = true
        }
        if (yaExiste) {
            return
        }
        val archivo = carpeta.createFile(TIPO, nombre)
        if (archivo == null) {
            throw IOException("No se pudo crear el archivo")
        }
        val salida = contexto.contentResolver.openOutputStream(archivo.uri, "w")
        if (salida == null) {
            throw IOException("No se pudo abrir el archivo")
        }
        salida.use { it.write(evento.aJson().toByteArray(Charsets.UTF_8)) }
        if (existentes != null) {
            existentes.add(nombre)
        }
    }
}
