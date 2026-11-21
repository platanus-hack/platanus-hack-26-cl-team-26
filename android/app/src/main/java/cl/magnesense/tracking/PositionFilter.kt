package cl.magnesense.tracking

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sqrt

/**
 * Limpia la posicion del iman antes de mostrarla o dibujar con ella.
 *
 * 1. Descarta lecturas con mal calce del modelo (iman inclinado, metal cerca, muy cerca).
 * 2. Descarta saltos bruscos (> [maxJumpCm] entre actualizaciones) salvo que la lectura
 *    siguiente los confirme: asi un error aislado no mueve el lapiz, pero un movimiento
 *    rapido real si.
 * 3. Filtro "One Euro" por eje: muy suave cuando el dedo va lento, rapido cuando va rapido.
 *
 * Kotlin puro: se prueba sin Android.
 */
class PositionFilter(
    private val minConfidence: Double = 0.5,
    private val maxJumpCm: Double = 2.5,
    private val confirmCm: Double = 1.0,
    private val minCutoffHz: Double = 1.0,
    private val beta: Double = 0.05,
    private val derivativeCutoffHz: Double = 1.0,
) {
    /** Lecturas descartadas desde el ultimo [reset]. */
    var rejected = 0
        private set

    private var lastRaw: TrackPoint? = null
    private var pending: TrackPoint? = null
    private val axes = Array(3) { OneEuro() }
    private var lastT = Double.NaN

    fun reset() {
        lastRaw = null
        pending = null
        axes.forEach { it.reset() }
        lastT = Double.NaN
        rejected = 0
    }

    /** Devuelve la posicion filtrada, o null si la lectura se descarto (mantener la anterior). */
    fun update(p: TrackPoint, confidence: Double, t: Double): TrackPoint? {
        if (confidence < minConfidence) {
            rejected++
            return null
        }
        val ref = lastRaw
        if (ref != null && dist(p, ref) > maxJumpCm) {
            val pend = pending
            if (pend == null || dist(p, pend) > confirmCm) {
                pending = p
                rejected++
                return null
            }
            // Dos lecturas seguidas coinciden: fue un movimiento real; el filtro salta con el.
            axes.forEach { it.reset() }
        }
        pending = null
        lastRaw = p
        val dt = if (lastT.isNaN()) 0.0 else (t - lastT).coerceAtLeast(1e-3)
        lastT = t
        return TrackPoint(axes[0].filter(p.x, dt), axes[1].filter(p.y, dt), axes[2].filter(p.z, dt))
    }

    private fun dist(a: TrackPoint, b: TrackPoint): Double {
        val dx = a.x - b.x
        val dy = a.y - b.y
        val dz = a.z - b.z
        return sqrt(dx * dx + dy * dy + dz * dz)
    }

    /** One Euro filter (Casiez et al., 2012) para un eje. */
    private inner class OneEuro {
        private var x = Double.NaN
        private var dx = 0.0

        fun reset() {
            x = Double.NaN
            dx = 0.0
        }

        fun filter(value: Double, dt: Double): Double {
            if (x.isNaN() || dt <= 0.0) {
                x = value
                dx = 0.0
                return value
            }
            val rawDx = (value - x) / dt
            dx += alpha(derivativeCutoffHz, dt) * (rawDx - dx)
            val cutoff = minCutoffHz + beta * abs(dx)
            x += alpha(cutoff, dt) * (value - x)
            return x
        }

        private fun alpha(cutoffHz: Double, dt: Double): Double {
            val tau = 1.0 / (2 * PI * cutoffHz)
            return 1.0 / (1.0 + tau / dt)
        }
    }
}
