package cl.magnesense.tracking

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.random.Random

class PositionFilterTest {

    private val dt = 0.05

    @Test
    fun lowConfidenceReadingIsHeld() {
        val f = PositionFilter()
        assertNotNull(f.update(TrackPoint(0.0, 0.0, 3.0), 0.9, 0.0))
        assertNull(f.update(TrackPoint(1.0, 0.0, 3.0), 0.3, dt))
        assertEquals(1, f.rejected)
    }

    @Test
    fun isolatedJumpIsIgnoredButConfirmedMoveIsFollowed() {
        val f = PositionFilter()
        f.update(TrackPoint(0.0, 0.0, 3.0), 0.9, 0.0)
        // Un error aislado: salta 5 cm y vuelve.
        assertNull(f.update(TrackPoint(5.0, 0.0, 3.0), 0.9, dt))
        val back = f.update(TrackPoint(0.1, 0.0, 3.0), 0.9, 2 * dt)
        assertNotNull(back)
        assertTrue("no debe saltar: ${back!!.x}", back.x < 0.5)
        // Un movimiento real: dos lecturas seguidas en el lugar nuevo.
        assertNull(f.update(TrackPoint(4.0, 0.0, 3.0), 0.9, 3 * dt))
        val moved = f.update(TrackPoint(4.1, 0.0, 3.0), 0.9, 4 * dt)
        assertNotNull(moved)
        assertEquals(4.1, moved!!.x, 0.01)
    }

    @Test
    fun jitterIsReducedWhileHoldingStill() {
        val f = PositionFilter()
        val rnd = Random(3)
        val out = (0 until 100).mapNotNull { i ->
            f.update(TrackPoint(2.0 + rnd.nextDouble(-0.3, 0.3), 0.0, 3.0), 0.9, i * dt)
        }.drop(20)
        // Entrada: uniforme ±0,3 cm → RMS ≈ 0,17 cm. Debe bajar a menos de la mitad.
        val rms = kotlin.math.sqrt(out.sumOf { (it.x - 2.0) * (it.x - 2.0) } / out.size)
        assertTrue("RMS del temblor: $rms", rms < 0.08)
        assertTrue(out.maxOf { abs(it.x - 2.0) } < 0.25)
    }

    @Test
    fun followsASteadyMovementWithLittleLag() {
        val f = PositionFilter()
        var last: TrackPoint? = null
        for (i in 0 until 40) last = f.update(TrackPoint(i * 0.1, 0.0, 3.0), 0.9, i * dt)   // 2 cm/s
        assertEquals(3.9, last!!.x, 0.4)
    }
}
