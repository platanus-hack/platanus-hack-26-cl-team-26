package cl.magnesense.gestures.local

import cl.magnesense.detector.Vec3
import kotlin.math.abs

/**
 * Direccion aprendida de los ejemplos (port de DirectionModel en detectors.py).
 * [peak] es la mediana de la proyeccion maxima de los ejemplos (µT).
 */
data class DirectionModel(val u: Vec3, val peak: Double, val minCos: Double = 0.6) {

    /** Coseno minimo entre la direccion y el pico de cada ejemplo (1 = identicos). */
    fun consistency(examples: List<List<Vec3>>): Double =
        examples.filter { it.isNotEmpty() }
            .minOfOrNull { ex -> val p = ex.maxBy { it.norm }; abs(p dot u) / maxOf(p.norm, 1e-9) } ?: 0.0

    companion object {
        /** [examples]: el cambio (B − reposo) de cada ejemplo. Acepta las dos caras del iman. */
        fun fit(examples: List<List<Vec3>>): DirectionModel {
            val peaks = examples.filter { it.isNotEmpty() }.map { ex -> ex.maxBy { it.norm } }
            require(peaks.isNotEmpty()) { "sin ejemplos" }
            val units = peaks.map { it.normalized() }
            val ref = units[0]
            val aligned = units.map { if ((it dot ref) < 0) it * -1.0 else it }
            val u = (aligned.fold(Vec3.ZERO) { a, b -> a + b } / aligned.size.toDouble()).normalized()
            return DirectionModel(u, median(peaks.map { abs(it dot u) }))
        }

        private fun median(xs: List<Double>): Double {
            val s = xs.sorted()
            val n = s.size
            return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2
        }
    }
}

/** Un evento de un gesto aprendido. [kind]: start | end | short | long | double | drift | stuck | too_strong. */
data class GestureEvent(val detector: String, val kind: String, val t: Double, val duration: Double? = null, val signal: Double? = null)

/**
 * Gesto puntual con duracion minima, histeresis y clasificacion (port de EventDetector).
 *
 * - Umbral k·σ con piso [floor], ajustado a la fuerza de los ejemplos.
 * - Exige un cambio rapido (en menos de [riseWindow]) para ignorar derivas.
 * - Un cambio mas fuerte que [maxRatio] veces lo aprendido es un golpe, no el gesto.
 */
class EventGestureDetector(
    val name: String,
    val direction: DirectionModel?,
    private val k: Double = 6.0,
    private val floor: Double = 1.0,
    val minOn: Double = 0.16,
    private val minOff: Double = 0.10,
    private val longSeconds: Double = 0.8,
    private val doubleGap: Double = 0.5,
    private val stuckAfter: Double = 6.0,
    private val peakFrac: Double = 0.4,
    private val riseWindow: Double = 2.0,
    private val riseFrac: Double = 0.7,
    private val maxRatio: Double = 1.6,
) {
    /** El iman cuenta por cualquiera de sus caras; el banco lo apaga si otro gesto usa la contraria. */
    var bipolar = true

    var active = false
        private set
    var signal = 0.0
        private set
    var count = 0
        private set
    var aboveSince: Double? = null
        private set

    private var belowSince: Double? = null
    private var activeSince = 0.0
    private var pendingShortEnd: Double? = null
    private val history = ArrayDeque<Pair<Double, Double>>()
    private var onsetMin = 0.0
    private var vetoed = false

    fun threshold(noise: Double): Double {
        var thr = maxOf(k * noise, floor)
        val d = direction ?: return thr
        thr = maxOf(thr, peakFrac * d.peak)
        // Que los propios ejemplos alcancen: como mucho 60 % del pico, nunca bajo 3σ.
        return minOf(thr, maxOf(0.6 * d.peak, 3 * noise, floor))
    }

    /** Senal maxima aceptada antes de activar (0 = sin tope). */
    fun cap(noise: Double): Double {
        val d = direction ?: return 0.0
        if (maxRatio <= 0) return 0.0
        return maxOf(maxRatio * d.peak, d.peak + 10 * noise)
    }

    private fun signalOf(delta: Vec3, raw: Vec3): Pair<Double, Double> {
        val d = direction ?: return delta.norm to raw.norm
        var s = delta dot d.u
        var r = raw dot d.u
        if (bipolar) {
            s = abs(s)
            r = abs(r)
        }
        val mag = delta.norm
        if (mag > 1e-9 && abs(s) / mag < d.minCos) s = 0.0
        return maxOf(s, 0.0) to maxOf(r, 0.0)
    }

    /** [suppress]: otro gesto se parece mas a este cambio; no empezar. */
    fun step(t: Double, delta: Vec3, raw: Vec3, noise: Double, suppress: Boolean = false): List<GestureEvent> {
        val ev = ArrayList<GestureEvent>(2)
        var (sig, rawSig) = signalOf(delta, raw)
        if (suppress && !active) {
            sig = 0.0
            rawSig = 0.0
        }
        signal = sig
        val thr = threshold(noise)
        history.addLast(t to sig)
        while (history.isNotEmpty() && t - history.first().first > riseWindow + 1.0) history.removeFirst()

        pendingShortEnd?.let { end ->
            if (!active && aboveSince == null && t - end > doubleGap) {
                ev += gesture("short", t)
                pendingShortEnd = null
            }
        }

        if (!active) {
            if (vetoed) {
                if (sig < thr / 2) vetoed = false else sig = 0.0 // esperar a que el iman se aleje
            }
            val cap = cap(noise)
            if (cap > 0 && sig > cap && !vetoed) {
                vetoed = true
                aboveSince = null
                ev += GestureEvent(name, "too_strong", t, signal = sig)
                sig = 0.0
            }
            if (sig > thr && rawSig > thr / 2) {
                val since = aboveSince ?: t.also {
                    aboveSince = it
                    onsetMin = history.filter { (ht, _) -> ht >= t - riseWindow && ht < t }.minOfOrNull { it.second } ?: 0.0
                }
                if (t - since >= minOn) {
                    if (sig - onsetMin >= riseFrac * thr) {
                        active = true
                        activeSince = since
                        belowSince = null
                        ev += GestureEvent(name, "start", t, signal = sig)
                    } else if (t - since >= riseWindow) {
                        // Cruzo el umbral sin un cambio rapido: deriva, no gesto.
                        aboveSince = null
                        ev += GestureEvent(name, "drift", t)
                    }
                }
            } else {
                aboveSince = null
            }
        } else if (sig < thr / 2) {
            val below = belowSince ?: t.also { belowSince = it }
            if (t - below >= minOff) {
                val dur = below - activeSince
                active = false
                aboveSince = null
                ev += GestureEvent(name, "end", t, duration = dur)
                when {
                    dur >= longSeconds -> {
                        if (pendingShortEnd != null) {
                            ev += gesture("short", t)
                            pendingShortEnd = null
                        }
                        ev += gesture("long", t, dur)
                    }
                    pendingShortEnd != null -> {
                        pendingShortEnd = null
                        ev += gesture("double", t)
                    }
                    else -> pendingShortEnd = t
                }
            }
        } else {
            belowSince = null
            if (t - activeSince >= stuckAfter) {
                active = false
                aboveSince = null
                pendingShortEnd = null
                ev += GestureEvent(name, "end", t, duration = t - activeSince)
                ev += GestureEvent(name, "stuck", t)
            }
        }
        return ev
    }

    private fun gesture(kind: String, t: Double, dur: Double? = null): GestureEvent {
        count++
        return GestureEvent(name, kind, t, duration = dur)
    }
}
