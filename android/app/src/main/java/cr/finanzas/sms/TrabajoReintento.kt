package cr.finanzas.sms

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequest
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/** Reintenta la cola con espera exponencial (30 s, 1 min, 2 min… hasta 5 h) hasta vaciarla. */
class TrabajoReintento(contexto: Context, parametros: WorkerParameters) : Worker(contexto, parametros) {

    override fun doWork(): Result {
        if (Entrega.vaciarCola(applicationContext)) {
            return Result.success()
        }
        return Result.retry()
    }

    companion object {
        private const val NOMBRE = "vaciar-cola"

        fun programar(contexto: Context) {
            val peticion = OneTimeWorkRequest.Builder(TrabajoReintento::class.java)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(contexto.applicationContext)
                .enqueueUniqueWork(NOMBRE, ExistingWorkPolicy.KEEP, peticion)
        }
    }
}
