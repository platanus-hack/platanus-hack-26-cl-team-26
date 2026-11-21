package cl.magnesense.tracking

import cl.magnesense.detector.Vec3
import cl.magnesense.sensor.SensorSink
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Lo que muestra la pestana 3D. */
data class TrackerUiState(
    val result: TrackResult = TrackResult(TrackState.NO_BASE),
    val trail: List<TrackPoint> = emptyList(),
    val hasBase: Boolean = false,
    val calibrated: Boolean = false,
    val refCm: Double? = null,
    /** El giroscopio ve que el celular se mueve: no se calcula la posicion. */
    val phoneMoving: Boolean = false,
)

/**
 * Conecta los sensores con [MagnetTracker]: suaviza el magnetometro (τ = 40 ms, como el
 * servidor), resuelve la posicion como maximo cada [SOLVE_PERIOD_S] y publica el estado.
 * Sin compensacion por giro: si el celular se mueve, se pausa (debe estar quieto).
 */
class LiveTracker : SensorSink {

    val tracker = MagnetTracker()

    private val _state = MutableStateFlow(TrackerUiState())
    val state: StateFlow<TrackerUiState> = _state.asStateFlow()

    private var smooth: Vec3? = null
    private var lastT = Double.NaN
    private var lastSolveT = Double.NEGATIVE_INFINITY
    private var lastMotionT = Double.NEGATIVE_INFINITY

    override fun onMagnetometer(tNanos: Long, value: Vec3) {
        val t = tNanos / NANOS
        val dt = if (lastT.isNaN()) 0.0 else (t - lastT).coerceIn(0.0, 0.5)
        lastT = t
        val s = smooth?.approach(value, if (dt > 0) dt / (SMOOTH_TAU + dt) else 1.0) ?: value
        smooth = s
        tracker.push(s)
        if (t - lastSolveT < SOLVE_PERIOD_S) return
        lastSolveT = t
        val moving = t - lastMotionT < STILL_AFTER_S
        val result = if (moving) tracker.last else tracker.update()
        publish(result, moving)
    }

    override fun onGyroscope(tNanos: Long, value: Vec3) {
        if (value.norm > GYRO_LIMIT) lastMotionT = tNanos / NANOS
    }

    /** Paso 1 de la calibracion. Devuelve un mensaje de error, o null si salio bien. */
    fun measureBase(): String? = runStep { tracker.setBase() }

    /** Paso 2. Devuelve el resultado o lanza [TrackerException] con un mensaje para mostrar. */
    fun calibrate(distCm: Double): MagnetCalibration = tracker.calibrate(distCm).also { publish(tracker.last, false) }

    fun reset() {
        tracker.reset()
        publish(tracker.last, false)
    }

    private fun runStep(block: () -> Unit): String? = try {
        block()
        publish(tracker.last, false)
        null
    } catch (e: TrackerException) {
        e.message
    }

    private fun publish(result: TrackResult, moving: Boolean) {
        _state.value = TrackerUiState(
            result = result,
            trail = tracker.trail(),
            hasBase = tracker.hasBase,
            calibrated = tracker.isCalibrated,
            refCm = tracker.refCm,
            phoneMoving = moving,
        )
    }

    private companion object {
        const val NANOS = 1e9
        const val SMOOTH_TAU = 0.04
        /** ~20 actualizaciones por segundo: suficiente para verlo fluido, liviano para la CPU. */
        const val SOLVE_PERIOD_S = 0.05
        const val GYRO_LIMIT = 0.3
        const val STILL_AFTER_S = 0.5
    }
}
