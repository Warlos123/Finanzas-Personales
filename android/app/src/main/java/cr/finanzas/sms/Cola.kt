package cr.finanzas.sms

import android.content.ContentValues
import android.content.Context
import android.database.DatabaseUtils
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * Base local (privada de la app):
 * - `pendientes`: eventos que no se pudieron escribir en la carpeta; se reintentan.
 * - `exportados`: solo los event_id ya escritos, para no duplicar archivos. Sin cuerpo del SMS.
 */
class Cola private constructor(contexto: Context) :
    SQLiteOpenHelper(contexto, "finanzas_sms.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE pendientes (event_id TEXT PRIMARY KEY, recibido_en TEXT NOT NULL, " +
                "cuerpo TEXT NOT NULL, creado INTEGER NOT NULL)"
        )
        db.execSQL("CREATE TABLE exportados (event_id TEXT PRIMARY KEY, exportado_en INTEGER NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, anterior: Int, nueva: Int) {}

    fun yaExportado(eventId: String): Boolean {
        val cantidad = DatabaseUtils.queryNumEntries(
            readableDatabase, "exportados", "event_id = ?", arrayOf(eventId)
        )
        return cantidad > 0
    }

    fun marcarExportado(eventId: String) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val valores = ContentValues()
            valores.put("event_id", eventId)
            valores.put("exportado_en", System.currentTimeMillis())
            db.insertWithOnConflict("exportados", null, valores, SQLiteDatabase.CONFLICT_IGNORE)
            db.delete("pendientes", "event_id = ?", arrayOf(eventId))
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun encolar(evento: Evento) {
        val valores = ContentValues()
        valores.put("event_id", evento.eventId)
        valores.put("recibido_en", evento.recibidoEn)
        valores.put("cuerpo", evento.cuerpo)
        valores.put("creado", System.currentTimeMillis())
        writableDatabase.insertWithOnConflict("pendientes", null, valores, SQLiteDatabase.CONFLICT_IGNORE)
    }

    fun pendientes(): List<Evento> {
        val lista = ArrayList<Evento>()
        val cursor = readableDatabase.query(
            "pendientes", arrayOf("event_id", "recibido_en", "cuerpo"), null, null, null, null, "creado"
        )
        cursor.use {
            while (it.moveToNext()) {
                lista.add(Evento(it.getString(0), it.getString(1), it.getString(2)))
            }
        }
        return lista
    }

    fun cantidadPendientes(): Long = DatabaseUtils.queryNumEntries(readableDatabase, "pendientes")

    companion object {
        @Volatile
        private var instancia: Cola? = null

        fun de(contexto: Context): Cola {
            synchronized(this) {
                var actual = instancia
                if (actual == null) {
                    actual = Cola(contexto.applicationContext)
                    instancia = actual
                }
                return actual
            }
        }
    }
}
