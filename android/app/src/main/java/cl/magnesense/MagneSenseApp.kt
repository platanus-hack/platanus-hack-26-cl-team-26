package cl.magnesense

import android.app.Application
import cl.magnesense.engine.Engine
import cl.magnesense.sensor.SensorHub

/** Punto de entrada: crea los objetos compartidos por el servicio y la interfaz. */
class MagneSenseApp : Application() {

    lateinit var engine: Engine
        private set

    override fun onCreate() {
        super.onCreate()
        engine = Engine()
        SensorHub.sink = engine
    }
}
