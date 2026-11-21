package cl.magnesense

import android.app.Application
import cl.magnesense.actions.DeviceActions
import cl.magnesense.engine.AccessController
import cl.magnesense.engine.Engine
import cl.magnesense.feedback.Haptics
import cl.magnesense.feedback.Speaker
import cl.magnesense.sensor.SensorHub
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/** Punto de entrada: crea los objetos compartidos por el servicio y la interfaz. */
class MagneSenseApp : Application() {

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    lateinit var engine: Engine
        private set
    lateinit var access: AccessController
        private set

    override fun onCreate() {
        super.onCreate()
        engine = Engine()
        SensorHub.sink = engine
        access = AccessController(
            scope = scope,
            detectorEvents = engine.events,
            actions = DeviceActions(this),
            speaker = Speaker(this),
            haptics = Haptics(this),
        )
    }
}
