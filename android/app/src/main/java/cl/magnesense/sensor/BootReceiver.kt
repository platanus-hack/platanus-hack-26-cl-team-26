package cl.magnesense.sensor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import cl.magnesense.MagneSenseApp

/** Inicia la deteccion al encender el telefono, solo si el cuidador lo activo en ajustes. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val app = context.applicationContext as MagneSenseApp
        if (app.settings.settings.value.startOnBoot) {
            runCatching { SensorService.start(context) }
        }
    }
}
