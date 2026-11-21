package cl.magnesense.gestures.local

import cl.magnesense.detector.Vec3
import kotlin.math.sqrt

/**
 * Suavizado y linea base para los gestos aprendidos (port de Pipeline en detectors.py).
 *
 * La linea base solo se mueve en reposo. Si hay una direccion aprendida, lo que cambia fuera
 * de ella se absorbe mas rapido (posturas, derivas) y lo de la direccion mas lento.
 * El giroscopio solo pausa: compensar el giro con el magnetometro sin calibrar invento
 * cambios de 1-3 µT por grado y provoco falsos positivos.
 */
class GesturePipeline(
    private val smoothTau: Double = 0.04,
    private val baselineTau: Double = 4.0,
    private val offAxisTau: Double = 1.5,
    val calibSeconds: Double = 2.0,
    /** Descarta el toque en la pantalla al pedir calibrar. */
    val calibSkip: Double = 0.5,
    /** rad/s: sobre esto el telefono se esta moviendo (~6°/s). */
    private val gyroMoving: Double = 0.1,
    /** s quieto tras moverse antes de volver a detectar. */
    private val settleSeconds: Double = 0.6,
) {
    var direction: Vec3? = null

    var smooth: Vec3? = null
        private set
    var baseline: Vec3? = null
        private set
    var noise = 0.0
        private set
    var lastT: Double? = null
        private set

    /** true mientras un detector esta activo: la base no se mueve. */
    var hold = false
    var gyroSeen = false
        private set

    private val calib = ArrayList<Vec3>()
    private var calibT0: Double? = null
    private var movingUntil = Double.NEGATIVE_INFINITY
    private var moved = false

    val calibrating: Boolean get() = baseline == null

    fun recalibrate() {
        baseline = null
        calib.clear()
        calibT0 = null
    }

    fun gyro(t: Double, w: Vec3) {
        gyroSeen = true
        if (w.norm > gyroMoving) {
            movingUntil = t + settleSeconds
            moved = true
        }
    }

    fun phoneMoving(t: Double) = t < movingUntil

    /** Devuelve el cambio respecto al reposo, o null mientras calibra. */
    fun step(t: Double, v: Vec3): Vec3? {
        val dt = lastT?.let { (t - it).coerceIn(0.0, 0.5) } ?: 0.0
        lastT = t
        val s = smooth?.let { if (dt > 0) it.approach(v, dt / (smoothTau + dt)) else v } ?: v
        smooth = s

        val base = baseline
        if (base == null) {
            val t0 = calibT0 ?: t.also { calibT0 = it }
            if (t - t0 < calibSkip) return null
            calib += s
            if (t - t0 >= calibSkip + calibSeconds && calib.size >= MIN_CALIB_SAMPLES) {
                val mean = calib.fold(Vec3.ZERO) { a, b -> a + b } / calib.size.toDouble()
                baseline = mean
                noise = sqrt(calib.sumOf { (it - mean) dot (it - mean) } / calib.size)
                calib.clear()
            }
            return null
        }

        if (moved && !phoneMoving(t)) {
            // Se movio y ya esta quieto: la posicion nueva es el reposo.
            baseline = s
            moved = false
            return Vec3.ZERO
        }
        val delta = s - base
        val mag = delta.norm
        val thr0 = maxOf(6 * noise, 1.0)
        val rest = !hold && !phoneMoving(t) && mag < thr0
        val gray = mag >= thr0 / 2
        if (rest && dt > 0) {
            val tau = if (gray) 20.0 else baselineTau
            val u = direction
            baseline = if (u == null) {
                base + delta * (dt / tau)
            } else {
                val along = u * (delta dot u)
                val off = delta - along
                base + along * (dt / tau) + off * (dt / offAxisTau)
            }
            if (!gray) {
                val a = dt / baselineTau
                noise = sqrt(noise * noise + a * (mag * mag - noise * noise))
            }
        }
        return delta
    }

    /** Toma la posicion actual como reposo (tras una deriva). */
    fun rebaseline() {
        smooth?.let { baseline = it }
    }

    private companion object {
        const val MIN_CALIB_SAMPLES = 10
    }
}
