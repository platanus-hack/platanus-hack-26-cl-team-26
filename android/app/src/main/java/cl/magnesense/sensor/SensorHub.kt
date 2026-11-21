package cl.magnesense.sensor

import cl.magnesense.detector.Vec3
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Lecturas crudas mas recientes, para la pantalla de depuracion y los chips de estado. */
data class SensorSnapshot(
    val running: Boolean = false,
    val magSensorName: String = "",
    val magUncalibrated: Boolean = false,
    val magMaxRange: Double = 0.0,
    val mag: Vec3 = Vec3.ZERO,
    /** |B| con el sesgo del sensor restado: deberia parecerse al campo terrestre (25-65 µT). */
    val earthField: Double = 0.0,
    val gyroAvailable: Boolean = false,
    val gyro: Vec3 = Vec3.ZERO,
    val magRateHz: Double = 0.0,
    val gyroRateHz: Double = 0.0,
)

/** Recibe cada muestra en el hilo de sensores (sin limitar). */
interface SensorSink {
    /** Se llama una vez al registrar los sensores. */
    fun onSensorsStarted(magMaxRange: Double, gyroAvailable: Boolean) = Unit

    /** [tNanos] es SystemClock.elapsedRealtimeNanos() del evento. */
    fun onMagnetometer(tNanos: Long, value: Vec3)
    fun onGyroscope(tNanos: Long, value: Vec3)
}

/** Punto de encuentro entre el servicio de sensores y el resto de la app. */
object SensorHub {
    private val _snapshot = MutableStateFlow(SensorSnapshot())
    val snapshot: StateFlow<SensorSnapshot> = _snapshot.asStateFlow()

    @Volatile
    var sink: SensorSink? = null

    internal fun publish(s: SensorSnapshot) {
        _snapshot.value = s
    }
}
