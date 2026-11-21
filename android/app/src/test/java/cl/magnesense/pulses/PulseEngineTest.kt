package cl.magnesense.pulses

import cl.magnesense.detector.Vec3
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import kotlin.math.ln
import kotlin.math.sqrt
import kotlin.random.Random

/** Pulsos sinteticos a 200 Hz con ruido σ ≈ 0,17 µT, como lo medido. */
class PulseEngineTest {

    private val earth = Vec3(20.0, -5.0, -40.0)
    private val dir = Vec3(0.3, 1.0, 0.2).normalized()
    private val rnd = Random(11)
    private lateinit var engine: PulseEngine
    private var t = 0.0
    private val events = ArrayList<PulseEvent>()
    private val rejected = ArrayList<String>()
    /** Campo extra fijo (p. ej. tras girar el celular). */
    private var offset = Vec3.ZERO

    @Before
    fun setUp() {
        engine = PulseEngine()
        t = 0.0
        events.clear()
        rejected.clear()
    }

    private fun gauss(): Double {
        var u: Double
        var v: Double
        var s: Double
        do {
            u = rnd.nextDouble() * 2 - 1
            v = rnd.nextDouble() * 2 - 1
            s = u * u + v * v
        } while (s >= 1 || s == 0.0)
        return u * sqrt(-2 * ln(s) / s)
    }

    private fun run(seconds: Double, extra: (Double) -> Vec3 = { Vec3.ZERO }) {
        val t0 = t
        while (t < t0 + seconds) {
            val r = engine.step(t, earth + offset + Vec3(gauss(), gauss(), gauss()) * 0.1 + extra(t - t0))
            events += r.events
            rejected += r.rejected.map { it.first }
            t += DT
        }
    }

    /** Pulso del iman de [ms] (con subida y bajada de 20 ms) y luego [gap] s de silencio. */
    private fun pulse(ms: Int, ut: Double = 5.0, gap: Double = 0.25) {
        val hold = ms / 1000.0
        run(hold) { s -> dir * (ut * minOf(s / 0.02, 1.0, (hold - s) / 0.02).coerceAtLeast(0.0)) }
        run(gap)
    }

    private fun codes() = events.filterIsInstance<PulseEvent.Code>().map { it.code }
    private fun pulses() = events.filterIsInstance<PulseEvent.Pulse>()

    private fun calibrate() {
        run(4.5)
        events.clear()
    }

    @Test
    fun shortAndLongMakeASequence() {
        calibrate()
        pulse(150)
        pulse(700)
        run(1.5)
        assertEquals(listOf(".-"), codes())
        assertEquals(PulseEvent.Code(".-", "A"), events.filterIsInstance<PulseEvent.Code>().first())
    }

    @Test
    fun durationIsMeasuredFromTheCrossing() {
        calibrate()
        pulse(300)
        run(1.5)
        val d = pulses().single().dur
        // Desde que cruza el umbral (no desde que se confirma a los 60 ms) hasta que baja de la mitad;
        // el suavizado de 40 ms alarga un poco la bajada, igual al aprender el ritmo que al usarlo.
        assertTrue("duracion $d", d > 0.28 && d < 0.42)
    }

    @Test
    fun veryShortBlipIsIgnored() {
        calibrate()
        pulse(40)
        run(1.5)
        assertTrue(pulses().isEmpty())
    }

    @Test
    fun silenceSeparatesSequencesAndWords() {
        calibrate()
        pulse(150)
        run(1.2)
        pulse(150)
        pulse(150)
        run(3.0)
        assertEquals(listOf(".", ".."), codes())
        assertTrue(events.last() is PulseEvent.Space)
    }

    @Test
    fun learnTimingAdaptsDotLimit() {
        calibrate()
        engine.startTiming()
        repeat(3) { pulse(300, gap = 0.4) }
        repeat(3) { pulse(1000, gap = 0.4) }
        val timing = events.filterIsInstance<PulseEvent.Timing>().single()
        assertTrue(timing.ok)
        assertTrue("dotMax ${engine.decoder.dotMax}", engine.decoder.dotMax in 0.55..0.7)
        events.clear()
        run(1.5)
        pulse(400) // antes habria sido raya
        run(1.5)
        assertEquals(listOf("."), codes())
    }

    @Test
    fun hitAfterLearningIsDiscarded() {
        calibrate()
        engine.startTiming()
        repeat(3) { pulse(200, gap = 0.4) }
        repeat(3) { pulse(800, gap = 0.4) }
        events.clear()
        run(1.5)
        pulse(200, ut = 40.0)
        run(1.5)
        assertTrue(codes().isEmpty())
        assertTrue(rejected.contains("too_strong"))
    }

    @Test
    fun slowDriftIsNotAPulse() {
        calibrate()
        run(25.0) { s -> dir * (0.2 * s) }
        run(3.0) { dir * 5.0 }
        assertTrue(pulses().isEmpty())
    }

    @Test
    fun phoneRotationIsNotAPulse() {
        calibrate()
        val t0 = t
        while (t < t0 + 1.0) {
            engine.gyro(t, Vec3(0.0, 0.0, 1.0))
            events += engine.step(t, earth + Vec3(8.0, 0.0, 0.0) * (t - t0)).events
            t += DT
        }
        offset = Vec3(8.0, 0.0, 0.0)
        run(2.0)
        assertTrue(pulses().isEmpty())
        pulse(150) // con la base nueva sigue funcionando
        run(1.5)
        assertEquals(listOf("."), codes())
    }

    @Test
    fun nothingWhileCalibrating() {
        run(0.2)
        pulse(150)
        run(4.0)
        assertTrue(codes().isEmpty())
    }

    @Test
    fun morseTable() {
        assertEquals("SOS", listOf("...", "---", "...").joinToString("") { PulseDecoder.MORSE.getValue(it) })
        assertEquals("Ñ", PulseDecoder.MORSE["--.--"])
    }

    private companion object {
        const val DT = 1.0 / 200
    }
}
