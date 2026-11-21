package cl.magnesense.tracking

import cl.magnesense.detector.Vec3
import cl.magnesense.sensor.SensorSink
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Lo que muestra la pestana 3D. */
data class TrackerUiState(
    val result: TrackResult = TrackResult(TrackState.NO_BASE),
    /** Posicion filtrada (sin saltos ni temblor): la que se dibuja y se muestra. */
    val display: TrackPoint? = null,
    /** La ultima lectura paso los filtros; false = se mantiene la posicion anterior. */
    val reliable: Boolean = false,
    /** Estela de posiciones filtradas. */
    val trail: List<TrackPoint> = emptyList(),
    /** Lecturas descartadas (mal calce o saltos) desde la ultima calibracion. */
    val rejected: Int = 0,
    val hasBase: Boolean = false,
    val calibrated: Boolean = false,
    val refCm: Double? = null,
    /** El giroscopio ve que el celular se mueve: no se calcula la posicion. */
    val phoneMoving: Boolean = false,
)

/**
 * Conecta los sensores con [MagnetTracker]: suaviza el magnetometro (τ = 40 ms, como el
 * servidor), resuelve la posicion como maximo cada [SOLVE_PERIOD_S], la limpia con
 * [PositionFilter] y publica el estado. Sin compensacion por giro: si el celular se mueve,
 * se pausa (debe estar quieto).
 */
class LiveTracker : SensorSink {

    val tracker = MagnetTracker()
    private val filter = PositionFilter()

    private val _state = MutableStateFlow(TrackerUiState())
    val state: StateFlow<TrackerUiState> = _state.asStateFlow()

    private var smooth: Vec3? = null
    private var lastT = Double.NaN
    private var lastSolveT = Double.NEGATIVE_INFINITY
    private var lastMotionT = Double.NEGATIVE_INFINITY
    private var display: TrackPoint? = null
    private val displayTrail = ArrayDeque<TrackPoint>()

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
        if (moving) {
            publish(tracker.last, moving = true, reliable = false)
            return
        }
        val result = tracker.update()
        val point = result.point
        var reliable = false
        if (result.state == TrackState.TRACKING && point != null) {
            filter.update(point, result.confidence, t)?.let {
                display = it
                displayTrail.addLast(it)
                while (displayTrail.size > TRAIL) displayTrail.removeFirst()
                reliable = true
            }
        } else if (result.state == TrackState.FAR) {
            // Al volver a acercarse no debe contar como un salto.
            filter.reset()
            display = null
        }
        publish(result, moving = false, reliable = reliable)
    }

    override fun onGyroscope(tNanos: Long, value: Vec3) {
        if (value.norm > GYRO_LIMIT) lastMotionT = tNanos / NANOS
    }

    /** Paso 1 de la calibracion. Devuelve un mensaje de error, o null si salio bien. */
    fun measureBase(): String? = try {
        tracker.setBase()
        clearPath()
        null
    } catch (e: TrackerException) {
        e.message
    }

    /** Paso 2. Devuelve el resultado o lanza [TrackerException] con un mensaje para mostrar. */
    fun calibrate(distCm: Double): MagnetCalibration = tracker.calibrate(distCm).also { clearPath() }

    fun reset() {
        tracker.reset()
        clearPath()
    }

    private fun clearPath() {
        filter.reset()
        display = null
        displayTrail.clear()
        publish(tracker.last, moving = false, reliable = false)
    }

    private fun publish(result: TrackResult, moving: Boolean, reliable: Boolean) {
        _state.value = TrackerUiState(
            result = result,
            display = display,
            reliable = reliable,
            trail = displayTrail.toList(),
            rejected = filter.rejected,
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
        const val TRAIL = 60
    }
}
