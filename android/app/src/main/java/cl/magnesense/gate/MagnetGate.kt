package cl.magnesense.gate

import cl.magnesense.detector.Vec3
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

enum class GatePhase { MEASURING, WAITING, CHARGING, DONE }

data class GateState(
    val phase: GatePhase = GatePhase.MEASURING,
    /** Anillo de carga, 0..1. */
    val progress: Double = 0.0,
    /** Intensidad para la animacion, 0..1. */
    val strength: Double = 0.0,
    val signalUt: Double = 0.0,
    val thresholdUt: Double = 0.0,
)

/**
 * "Puerta magnetica" de la intro: hay que acercar un iman y mantenerlo un momento para entrar.
 *
 * Mide el campo de fondo al empezar (el iman se asume lejos), y luego compara |B − base| con un
 * umbral adaptado al ruido (minimo [minThresholdUt], para que sirva un iman debil). Mientras la
 * senal lo supera, el anillo se llena en ~[chargeSeconds]; si se suelta, baja suave. Si el celular
 * se mueve (giroscopio), se pausa y se vuelve a medir el fondo: moverlo no cuenta como iman.
 *
 * Kotlin puro: se prueba sin Android.
 */
class MagnetGate(
    private val baselineSeconds: Double = 0.6,
    private val minThresholdUt: Double = 8.0,
    private val noiseFactor: Double = 6.0,
    private val fullStrengthUt: Double = 40.0,
    private val chargeSeconds: Double = 2.6,
    private val decayPerSecond: Double = 0.7,
    private val gyroLimit: Double = 0.3,
    private val driftTau: Double = 3.0,
) {
    private val samples = ArrayList<Vec3>()
    private var measureStart = Double.NaN
    private var baseline: Vec3? = null
    private var threshold = minThresholdUt
    private var lastT = Double.NaN
    private var progress = 0.0
    private var done = false

    fun update(t: Double, mag: Vec3, gyro: Vec3): GateState {
        val dt = if (lastT.isNaN()) 0.0 else (t - lastT).coerceIn(0.0, 0.2)
        lastT = t
        if (done) return GateState(GatePhase.DONE, 1.0, 1.0, 0.0, threshold)

        if (gyro.norm > gyroLimit) {
            // El celular se mueve: pausar y volver a medir el fondo cuando quede quieto.
            baseline = null
            samples.clear()
            measureStart = Double.NaN
            return GateState(GatePhase.MEASURING, progress, 0.0, 0.0, threshold)
        }

        val base = baseline ?: return measure(t, mag)
        val signal = (mag - base).norm
        val strength = (signal / fullStrengthUt).coerceIn(0.0, 1.0)
        return if (signal >= threshold) {
            val above = ((signal - threshold) / max(fullStrengthUt - threshold, 1.0)).coerceIn(0.0, 1.0)
            progress = min(1.0, progress + dt / chargeSeconds * (0.7 + 0.6 * above))
            if (progress >= 1.0) done = true
            GateState(if (done) GatePhase.DONE else GatePhase.CHARGING, progress, max(strength, 0.25), signal, threshold)
        } else {
            progress = max(0.0, progress - decayPerSecond * dt)
            // Sin iman: seguir la deriva lenta del fondo.
            if (dt > 0) baseline = base.approach(mag, min(dt / driftTau, 1.0))
            GateState(GatePhase.WAITING, progress, strength * 0.5, signal, threshold)
        }
    }

    private fun measure(t: Double, mag: Vec3): GateState {
        if (measureStart.isNaN()) measureStart = t
        samples += mag
        if (t - measureStart >= baselineSeconds && samples.size >= 5) {
            val base = Vec3(median(samples.map { it.x }), median(samples.map { it.y }), median(samples.map { it.z }))
            val rms = sqrt(samples.sumOf { val d = (it - base).norm; d * d } / samples.size)
            baseline = base
            threshold = max(minThresholdUt, noiseFactor * rms)
            samples.clear()
        }
        return GateState(GatePhase.MEASURING, progress, 0.0, 0.0, threshold)
    }

    private fun median(v: List<Double>): Double {
        val s = v.sorted()
        return if (s.size % 2 == 1) s[s.size / 2] else (s[s.size / 2 - 1] + s[s.size / 2]) / 2
    }
}
