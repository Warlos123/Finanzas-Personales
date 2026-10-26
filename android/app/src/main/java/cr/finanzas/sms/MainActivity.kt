package cr.finanzas.sms

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.TextView
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Pantalla única: carpeta, permisos, último evento, pendientes, backfill y batería. */
class MainActivity : Activity() {

    private lateinit var textoCarpeta: TextView
    private lateinit var textoPermisos: TextView
    private lateinit var textoUltimo: TextView
    private lateinit var textoPendientes: TextView
    private lateinit var textoBackfill: TextView
    private lateinit var textoBateria: TextView
    private lateinit var botonBackfill: Button

    override fun onCreate(estado: Bundle?) {
        super.onCreate(estado)
        setContentView(R.layout.activity_main)
        textoCarpeta = findViewById(R.id.textoCarpeta)
        textoPermisos = findViewById(R.id.textoPermisos)
        textoUltimo = findViewById(R.id.textoUltimo)
        textoPendientes = findViewById(R.id.textoPendientes)
        textoBackfill = findViewById(R.id.textoBackfill)
        textoBateria = findViewById(R.id.textoBateria)
        botonBackfill = findViewById(R.id.botonBackfill)

        findViewById<Button>(R.id.botonCarpeta).setOnClickListener { elegirCarpeta() }
        findViewById<Button>(R.id.botonPermisos).setOnClickListener { pedirPermisos() }
        findViewById<Button>(R.id.botonAjustesApp).setOnClickListener { abrirAjustesApp() }
        findViewById<Button>(R.id.botonReintentar).setOnClickListener { reintentar() }
        findViewById<Button>(R.id.botonBateria).setOnClickListener { quitarOptimizacion() }
        botonBackfill.setOnClickListener { backfill() }
    }

    override fun onResume() {
        super.onResume()
        actualizar()
    }

    private fun elegirCarpeta() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
        intent.addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION or
                Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        )
        startActivityForResult(intent, PEDIR_CARPETA)
    }

    @Deprecated("API de Activity del framework; suficiente para una sola pantalla")
    override fun onActivityResult(codigo: Int, resultado: Int, datos: Intent?) {
        super.onActivityResult(codigo, resultado, datos)
        if (codigo != PEDIR_CARPETA || resultado != RESULT_OK || datos == null) {
            return
        }
        val uri = datos.data
        if (uri == null) {
            return
        }
        contentResolver.takePersistableUriPermission(
            uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        )
        Ajustes.guardarCarpeta(this, uri)
        TrabajoReintento.programar(this)
        actualizar()
    }

    private fun tienePermisos(): Boolean {
        val recibir = checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED
        val leer = checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED
        return recibir && leer
    }

    private fun pedirPermisos() {
        requestPermissions(arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS), PEDIR_PERMISOS)
    }

    override fun onRequestPermissionsResult(codigo: Int, permisos: Array<out String>, resultados: IntArray) {
        super.onRequestPermissionsResult(codigo, permisos, resultados)
        actualizar()
    }

    private fun abrirAjustesApp() {
        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
    }

    private fun reintentar() {
        Thread {
            Entrega.vaciarCola(applicationContext)
            runOnUiThread { actualizar() }
        }.start()
    }

    private fun backfill() {
        if (!tienePermisos()) {
            textoBackfill.text = "Primero concede los permisos de SMS."
            return
        }
        botonBackfill.isEnabled = false
        textoBackfill.text = "Exportando…"
        Thread {
            val resultado = Backfill.ejecutar(applicationContext)
            runOnUiThread {
                textoBackfill.text = "${resultado.nuevos} nuevos, ${resultado.yaExportados} ya exportados, " +
                    "${resultado.enCola} en cola, ${resultado.sinComprobante} sin comprobante (ignorados)."
                botonBackfill.isEnabled = true
                actualizar()
            }
        }.start()
    }

    private fun quitarOptimizacion() {
        startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }

    private fun actualizar() {
        val uri = Ajustes.carpeta(this)
        if (uri == null) {
            textoCarpeta.text = "Sin elegir. Elige la carpeta compartida con Syncthing."
        } else if (Entrega.carpeta(this) == null) {
            textoCarpeta.text = "${uri.lastPathSegment} (sin permiso de escritura: elígela de nuevo)"
        } else {
            textoCarpeta.text = "${uri.lastPathSegment}"
        }

        if (tienePermisos()) {
            textoPermisos.text = "Concedidos."
        } else {
            textoPermisos.text = "Faltan. Si Android dice \"configuración restringida\": Ajustes de la app → ⋮ → " +
                "Permitir configuración restringida, y vuelve a conceder."
        }

        val ultimo = Ajustes.ultimoId(this)
        if (ultimo == null) {
            textoUltimo.text = "Ninguno todavía."
        } else {
            val hora = DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm")
                .withZone(ZoneId.systemDefault())
                .format(Instant.ofEpochMilli(Ajustes.ultimoMs(this)))
            textoUltimo.text = "Comprobante $ultimo, escrito el $hora."
        }

        textoPendientes.text = "${Cola.de(this).cantidadPendientes()} en cola."

        val energia = getSystemService(PowerManager::class.java)
        if (energia.isIgnoringBatteryOptimizations(packageName)) {
            textoBateria.text = "Sin optimización de batería. En Samsung, agrega también la app a " +
                "Batería → Límites de uso en segundo plano → Aplicaciones que nunca entran en suspensión."
        } else {
            textoBateria.text = "La optimización de batería está activa: Android puede atrasar o bloquear la captura."
        }
    }

    companion object {
        private const val PEDIR_CARPETA = 1
        private const val PEDIR_PERMISOS = 2
    }
}
