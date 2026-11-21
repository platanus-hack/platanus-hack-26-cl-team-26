package cl.magnesense.tracking

import cl.magnesense.detector.Vec3
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random

/**
 * Mismos casos que test_localize.py, con un iman simulado (dipolo ideal):
 * validan el calculo; la precision real depende de que el iman no se incline.
 */
class MagnetTrackerTest {

    private val earth = Vec3(20.0, -5.0, -40.0)
    private val mTrue = Vec3(0.1, 0.0, 1.0).normalized() * 0.236   // 10x3 mm, algo inclinado
    private val random = Random(11)

    private fun noise(s: Double = 0.05) = Vec3(gauss() * s, gauss() * s, gauss() * s)

    private fun gauss(): Double {
        val u = random.nextDouble().coerceAtLeast(1e-12)
        return kotlin.math.sqrt(-2 * kotlin.math.ln(u)) * cos(2 * Math.PI * random.nextDouble())
    }

    private fun calibrated(): Pair<MagnetTracker, MagnetCalibration> {
        val t = MagnetTracker()
        repeat(20) { t.push(earth + noise()) }
        t.setBase()
        repeat(20) { t.push(earth + MagnetTracker.field(Vec3(0.0, 0.0, 0.03), mTrue) + noise()) }
        return t to t.calibrate(3.0)
    }

    /** Error (mm) de cada muestra rastreada. */
    private fun track(t: MagnetTracker, path: List<Vec3>): List<Double> = path.mapNotNull { p ->
        t.push(earth + MagnetTracker.field(p, mTrue) + noise())
        val s = t.update()
        s.point?.takeIf { s.state == TrackState.TRACKING }?.let { (Vec3(it.x, it.y, it.z) / 100.0 - p).norm * 1000 }
    }

    @Test
    fun calibrationRecoversTheMagnet() {
        val (_, cal) = calibrated()
        assertEquals(0.236, cal.momentAm2, 0.002)
        assertEquals(5.7, cal.tiltDegrees, 0.3)
    }

    @Test
    fun followsCircleAndHeight() {
        val (t, _) = calibrated()
        val u = (0 until 300).map { it / 299.0 }
        val circle = u.map { a -> Vec3(0.02 * cos(6.28 * a), 0.02 * sin(6.28 * a), 0.04) }
        val lift = u.map { a -> Vec3(0.005, -0.005, 0.025 + 0.05 * a) }
        for (path in listOf(circle, lift)) {
            val errs = track(t, path)
            assertEquals(path.size, errs.size)
            assertTrue("error max ${errs.max()} mm", errs.max() < 1.0)
        }
    }

    @Test
    fun mirrorSideAndFarMagnet() {
        val (t, _) = calibrated()
        val errs = track(t, List(5) { Vec3(0.01, 0.01, 0.035) })
        assertTrue("error max ${errs.max()} mm", errs.max() < 1.0)
        t.push(earth + noise())
        assertEquals(TrackState.FAR, t.update().state)
    }

    @Test
    fun calibrationErrorsAreExplained() {
        val t = MagnetTracker()
        expectError("Faltan datos") { t.setBase() }
        repeat(20) { t.push(earth) }
        expectError("Primero mide sin imán") { t.calibrate(3.0) }
        t.setBase()
        repeat(20) { t.push(earth + noise()) }
        expectError("casi no cambia") { t.calibrate(3.0) }
        for (i in 0 until 20) t.push(earth + MagnetTracker.field(Vec3(0.0, 0.0, 0.03 + 0.002 * i), mTrue))
        expectError("moviendo") { t.calibrate(3.0) }
    }

    @Test
    fun movingFarLeftAtTableLevelStaysLeft() {
        val (t, _) = calibrated()
        val u = (0 until 200).map { it / 199.0 }
        val down = u.map { a -> Vec3(-0.03 * a, 0.0, 0.03 - 0.033 * a) }
        val left = u.drop(1).map { a -> Vec3(-0.03 - 0.04 * a, 0.0, -0.003) }
        val xs = mutableListOf<Double>()
        for (p in down + left) {
            t.push(earth + MagnetTracker.field(p, mTrue) + noise())
            val s = t.update()
            if (s.state == TrackState.TRACKING && p.x < -0.01) xs += s.point!!.x
        }
        assertTrue(xs.isNotEmpty())
        assertTrue("debe quedar a la izquierda: ${xs.takeLast(5)}", xs.max() < 0)
        assertEquals(-7.0, xs.last(), 0.3)
    }

    @Test
    fun linearSolveMatchesKnownSystem() {
        val a = Mat3(doubleArrayOf(2.0, 1.0, -1.0, -3.0, -1.0, 2.0, -2.0, 1.0, 2.0))
        val x = a.solve(Vec3(8.0, -11.0, -3.0))
        assertEquals(2.0, x.x, 1e-9)
        assertEquals(3.0, x.y, 1e-9)
        assertEquals(-1.0, x.z, 1e-9)
    }

    private fun expectError(fragment: String, block: () -> Unit) {
        try {
            block()
            fail("se esperaba un error con \"$fragment\"")
        } catch (e: TrackerException) {
            assertTrue("mensaje: ${e.message}", e.message!!.contains(fragment))
        }
    }
}
