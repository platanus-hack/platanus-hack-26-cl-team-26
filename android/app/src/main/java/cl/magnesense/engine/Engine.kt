package cl.magnesense.engine

import cl.magnesense.detector.Detector
import cl.magnesense.detector.DetectorEvent
import cl.magnesense.detector.Vec3
import cl.magnesense.sensor.SensorSink
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * Une los sensores con el detector. Recibe cada muestra en el hilo de sensores
 * y publica los eventos del detector para el resto de la app.
 */
class Engine(val detector: Detector = Detector()) : SensorSink {

    private val _events = MutableSharedFlow<DetectorEvent>(
        extraBufferCapacity = 64,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val events: SharedFlow<DetectorEvent> = _events.asSharedFlow()

    /** Oyentes adicionales de muestras crudas (p. ej. telemetria). */
    @Volatile
    var rawListener: SensorSink? = null

    override fun onSensorsStarted(magMaxRange: Double, gyroAvailable: Boolean) {
        detector.setSensorInfo(magMaxRange, gyroAvailable)
        rawListener?.onSensorsStarted(magMaxRange, gyroAvailable)
    }

    override fun onMagnetometer(tNanos: Long, value: Vec3) {
        emit(detector.processMagnetometer(tNanos / NANOS, value))
        rawListener?.onMagnetometer(tNanos, value)
    }

    override fun onGyroscope(tNanos: Long, value: Vec3) {
        emit(detector.processGyroscope(tNanos / NANOS, value))
        rawListener?.onGyroscope(tNanos, value)
    }

    private fun emit(list: List<DetectorEvent>) {
        for (e in list) _events.tryEmit(e)
    }

    private companion object {
        const val NANOS = 1e9
    }
}
