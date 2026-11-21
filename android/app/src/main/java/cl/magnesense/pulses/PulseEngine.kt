package cl.magnesense.pulses

import cl.magnesense.detector.Vec3
import cl.magnesense.gestures.local.EventGestureDetector
import cl.magnesense.gestures.local.GesturePipeline

/** Lo que pasa en una muestra: eventos del decodificador y descartes (para el registro). */
data class PulseStep(
    val events: List<PulseEvent> = emptyList(),
    /** "too_strong", "drift" o "stuck", con la senal en µT. */
    val rejected: List<Pair<String, Double>> = emptyList(),
    /** El iman acaba de cruzar el umbral (para el beep de inicio y la "directo"). */
    val started: Boolean = false,
)

/**
 * Pulsos sobre el mismo detector que los gestos aprendidos: calibracion sin el toque,
 * umbral max(6σ, 1 µT), pausa por giroscopio, anti-deriva y anti-golpe, sin acciones al calibrar.
 * La duracion de cada pulso se mide desde que la senal cruza el umbral, no desde que se confirma.
 * No es seguro entre hilos.
 */
class PulseEngine(val pipeline: GesturePipeline = GesturePipeline()) {

    val decoder = PulseDecoder()
    /** Sin direccion aprendida: cuenta |B − reposo| venga de donde venga. Minimo de 60 ms. */
    val detector = EventGestureDetector("pulso", direction = null, minOn = decoder.minPulse)

    private var muteUntil = Double.NEGATIVE_INFINITY
    private var wasCalibrating = true
    private var peak = 0.0
    private val learnPeaks = ArrayList<Double>()

    /** Ultimo |B − reposo| (µT) y umbral, para mostrar en vivo. */
    var signal = 0.0
        private set
    val threshold: Double get() = detector.threshold(pipeline.noise)
    val active: Boolean get() = detector.active

    fun gyro(t: Double, w: Vec3) = pipeline.gyro(t, w)

    fun recalibrate() {
        pipeline.recalibrate()
        decoder.reset()
        wasCalibrating = true
    }

    /** La persona hace 3 pulsos cortos y 3 largos. Tambien aprende su fuerza para el anti-golpe. */
    fun startTiming() {
        learnPeaks.clear()
        decoder.startTiming()
    }

    fun step(t: Double, v: Vec3): PulseStep {
        val p = pipeline
        var delta = p.step(t, v) ?: run {
            signal = 0.0
            return PulseStep()
        }
        if (wasCalibrating) {
            wasCalibrating = false
            muteUntil = t + MUTE_AFTER_S
            decoder.reset()
        }
        var raw = v - p.baseline!!
        if (p.phoneMoving(t)) {
            delta = Vec3.ZERO
            raw = Vec3.ZERO
        }
        signal = delta.norm
        val wasActive = detector.active
        val det = detector.step(t, delta, raw, p.noise)
        p.hold = detector.active
        if (detector.active) peak = maxOf(peak, detector.signal)

        val muted = t < muteUntil
        val events = ArrayList<PulseEvent>()
        val rejected = ArrayList<Pair<String, Double>>()
        val stuck = det.any { it.kind == "stuck" }
        for (e in det) {
            when (e.kind) {
                "too_strong" -> rejected += "too_strong" to (e.signal ?: 0.0)
                "drift" -> {
                    p.rebaseline()
                    rejected += "drift" to signal
                }
                "stuck" -> rejected += "stuck" to signal
                // Un iman que se quedo cerca 6 s no es una raya.
                "end" -> if (!stuck && !muted) {
                    val learning = decoder.learning
                    val out = decoder.onPulse(t, e.duration ?: 0.0)
                    if (learning) learnPeaks += peak
                    out.filterIsInstance<PulseEvent.Timing>().firstOrNull()?.let { if (it.ok) learnCap() }
                    events += out
                }
            }
            if (e.kind == "end") peak = 0.0
        }
        if (!muted) events += decoder.tick(t, detector.active)
        return PulseStep(events, rejected, started = !wasActive && detector.active && !muted)
    }

    /** Anti-golpe: mucho mas fuerte que los pulsos de la persona no es un pulso. */
    private fun learnCap() {
        if (learnPeaks.isEmpty()) return
        val median = learnPeaks.sorted()[learnPeaks.size / 2]
        detector.fixedCap = maxOf(MAX_RATIO * median, median + 10 * pipeline.noise)
    }

    /** Para restaurar un tope guardado. */
    fun setCap(cap: Double) {
        detector.fixedCap = cap
    }

    val cap: Double get() = detector.fixedCap

    companion object {
        const val MUTE_AFTER_S = 1.5
        const val MAX_RATIO = 1.6
    }
}
