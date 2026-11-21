package cl.magnesense.gestures.local

import cl.magnesense.detector.Vec3
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import kotlin.random.Random

/**
 * Pruebas con datos sinteticos a 200 Hz: campo terrestre + ruido (σ ≈ 0,17 µT, el medido) + iman.
 * Validan la logica portada de detectors.py; los aciertos reales salen de grabaciones.
 */
class GestureBankTest {

    private val earth = Vec3(20.0, -5.0, -40.0)
    private val left = Vec3(1.0, 0.2, 0.0).normalized()
    private val right = Vec3(0.0, 0.3, 1.0).normalized()
    private val rnd = Random(7)
    private lateinit var bank: GestureBank
    private var t = 0.0
    private val events = ArrayList<Pair<GestureEvent, Boolean>>()

    @Before
    fun setUp() {
        bank = GestureBank()
        t = 0.0
        events.clear()
    }

    private fun noise() = Vec3(rnd.nextGaussian(), rnd.nextGaussian(), rnd.nextGaussian()) * 0.1

    private fun run(seconds: Double, extra: (Double) -> Vec3 = { Vec3.ZERO }) {
        val t0 = t
        while (t < t0 + seconds) {
            events += bank.step(t, earth + noise() + extra(t - t0))
            t += DT
        }
    }

    /** Pulso del iman: sube en 50 ms, se queda y baja. */
    private fun pulse(dir: Vec3, ut: Double, hold: Double) = run(hold + 0.1) { s ->
        val ramp = (s / 0.05).coerceAtMost(1.0) * ((hold + 0.1 - s) / 0.05).coerceIn(0.0, 1.0)
        dir * (ut * ramp)
    }

    private fun calibrate() {
        run(3.0)
        assertFalse(bank.pipeline.calibrating)
    }

    private fun teach(name: String, dir: Vec3, ut: Double, trigger: String = "any", minOnMs: Int = 160): TrainOutcome {
        repeat(3) {
            assertEquals(null, bank.startRecording(name))
            run(0.3)
            pulse(dir, ut, 0.4)
            run(0.5)
            bank.stopRecording()
            run(2.0)
        }
        return bank.train(GestureSpec(name, name, trigger, minOnMs))
    }

    private fun fired(name: String, kind: String = "start") = events.count { (e, muted) -> !muted && e.detector == name && e.kind == kind }

    private fun gyroSpin(seconds: Double) {
        val t0 = t
        while (t < t0 + seconds) {
            bank.gyro(t, Vec3(0.0, 0.0, 1.0))
            events += bank.step(t, earth + noise() + Vec3(5.0, 0.0, 0.0) * (t - t0))
            t += DT
        }
    }

    @Test
    fun calibrationSkipsTheTouch() {
        // Toque en la pantalla al pedir calibrar: un pulso en los primeros 0,5 s no entra al reposo.
        run(0.4) { left * 3.0 }
        run(2.6)
        assertFalse(bank.pipeline.calibrating)
        val base = bank.pipeline.baseline!!
        assertTrue("base $base", (base - earth).norm < 0.2)
        assertTrue("ruido ${bank.pipeline.noise}", bank.pipeline.noise < 0.3)
    }

    @Test
    fun learnedGestureFiresWithWeakMagnet() {
        calibrate()
        val r = teach("cancion", left, 4.0)
        assertTrue(r.ok)
        assertTrue("consistencia ${r.consistency}", r.consistency!! > 0.95)
        events.clear()
        repeat(3) {
            pulse(left, 4.0, 0.4)
            run(1.5)
        }
        assertEquals(3, fired("cancion"))
    }

    @Test
    fun bothMagnetFacesCount() {
        calibrate()
        teach("cancion", left, 5.0)
        events.clear()
        pulse(left * -1.0, 5.0, 0.4)
        run(1.5)
        assertEquals(1, fired("cancion"))
    }

    @Test
    fun noActionsWhileRecordingOrJustAfter() {
        calibrate()
        teach("cancion", left, 5.0)
        events.clear()
        bank.startRecording("cancion")
        pulse(left, 5.0, 0.4)
        bank.stopRecording()
        pulse(left, 5.0, 0.4) // dentro de los 1,5 s de silencio
        assertEquals(0, fired("cancion"))
        run(2.0)
        pulse(left, 5.0, 0.4)
        run(1.0)
        assertEquals(1, fired("cancion"))
    }

    @Test
    fun shortTwitchIsIgnored() {
        calibrate()
        teach("cancion", left, 5.0)
        events.clear()
        pulse(left, 5.0, 0.08)
        run(1.5)
        assertEquals(0, fired("cancion"))
    }

    @Test
    fun twitchFilterNeeds300ms() {
        calibrate()
        teach("cancion", left, 5.0, minOnMs = 300)
        events.clear()
        pulse(left, 5.0, 0.2)
        run(1.5)
        assertEquals(0, fired("cancion"))
        pulse(left, 5.0, 0.5)
        run(1.5)
        assertEquals(1, fired("cancion"))
    }

    @Test
    fun hitMuchStrongerThanLearnedIsNotTheGesture() {
        calibrate()
        teach("cancion", left, 5.0)
        events.clear()
        pulse(left, 30.0, 0.4)
        run(1.5)
        assertEquals(0, fired("cancion"))
        assertTrue(events.any { it.first.kind == "too_strong" })
    }

    @Test
    fun slowDriftIsNotAGesture() {
        calibrate()
        teach("cancion", left, 5.0)
        events.clear()
        // Sube 5 µT en 25 s (un parlante o metal que se acerca lento), como en test_detectors.py.
        run(25.0) { s -> left * (0.2 * s) }
        run(3.0) { left * 5.0 }
        assertEquals(0, fired("cancion"))
    }

    @Test
    fun otherDirectionIsIgnored() {
        calibrate()
        teach("cancion", left, 5.0)
        events.clear()
        pulse(Vec3(0.0, 1.0, 0.0), 5.0, 0.4)
        run(1.5)
        assertEquals(0, fired("cancion"))
    }

    @Test
    fun twoGesturesFireOnlyTheClosest() {
        calibrate()
        teach("cancion", left, 5.0)
        teach("pato", right, 5.0)
        events.clear()
        pulse(right, 5.0, 0.4)
        run(1.5)
        assertEquals(1, fired("pato"))
        assertEquals(0, fired("cancion"))
    }

    @Test
    fun phoneRotationPausesAndRebaselines() {
        calibrate()
        teach("cancion", left, 5.0)
        events.clear()
        gyroSpin(1.0)
        run(2.0)
        assertEquals(0, fired("cancion"))
        // Despues del giro sigue funcionando con la base nueva.
        pulse(left, 5.0, 0.4)
        run(1.5)
        assertEquals(1, fired("cancion"))
    }

    @Test
    fun retrainingReplaces() {
        calibrate()
        teach("cancion", left, 5.0)
        bank.clearExamples("cancion")
        teach("cancion", right, 5.0)
        assertEquals(1, bank.detectors.size)
        events.clear()
        pulse(left, 5.0, 0.4)
        run(1.5)
        assertEquals(0, fired("cancion"))
        pulse(right, 5.0, 0.4)
        run(1.5)
        assertEquals(1, fired("cancion"))
    }

    private companion object {
        const val DT = 1.0 / 200
    }
}

private fun Random.nextGaussian(): Double {
    var u: Double
    var v: Double
    var s: Double
    do {
        u = nextDouble() * 2 - 1
        v = nextDouble() * 2 - 1
        s = u * u + v * v
    } while (s >= 1 || s == 0.0)
    return u * kotlin.math.sqrt(-2 * kotlin.math.ln(s) / s)
}
