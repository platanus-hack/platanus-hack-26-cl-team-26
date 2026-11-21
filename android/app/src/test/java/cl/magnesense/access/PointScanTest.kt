package cl.magnesense.access

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PointScanTest {

    // Sin compensacion ni margen, para que las cuentas sean exactas.
    private fun scan() = PointScan(xPassS = 4.0, yPassS = 4.0, maxPasses = 4, confirmS = 3.0, latencyS = 0.0, margin = 0f)

    @Test
    fun threePulsesTapTheChosenPoint() {
        val s = scan()
        s.start(10.0)
        assertEquals(ScanOutcome.None, s.pulse(11.0))          // x = 1/4
        assertEquals(ScanPhase.SWEEP_Y, s.phase)
        assertEquals(ScanOutcome.None, s.pulse(14.0))          // y = 3/4
        assertEquals(ScanPhase.CONFIRM, s.phase)
        val tap = s.pulse(15.0) as ScanOutcome.Tap
        assertEquals(0.25f, tap.x, 1e-4f)
        assertEquals(0.75f, tap.y, 1e-4f)
        assertEquals(ScanPhase.IDLE, s.phase)
    }

    @Test
    fun lineGoesBackAndForth() {
        val s = scan()
        s.start(0.0)
        assertEquals(0.5f, s.frame(2.0).x, 1e-4f)
        assertEquals(1.0f, s.frame(3.999).x, 1e-3f)
        assertEquals(0.75f, s.frame(5.0).x, 1e-4f)              // volviendo
    }

    @Test
    fun reactionTimeIsCompensated() {
        val s = PointScan(xPassS = 4.0, latencyS = 0.4, margin = 0f)
        s.start(0.0)
        s.pulse(2.4)                                           // se toma la posicion de t = 2,0
        assertEquals(0.5f, s.frame(2.5).fixedX!!, 1e-4f)
    }

    @Test
    fun cancelsAfterMaxPassesWithoutPulse() {
        val s = scan()
        s.start(0.0)
        assertEquals(ScanOutcome.None, s.tick(15.9))
        assertEquals(ScanOutcome.Cancelled, s.tick(16.1))
        assertEquals(ScanPhase.IDLE, s.phase)
    }

    @Test
    fun confirmationExpiresIntoCancel() {
        val s = scan()
        s.start(0.0)
        s.pulse(1.0)
        s.pulse(2.0)
        assertEquals(ScanOutcome.None, s.tick(4.9))
        assertEquals(ScanOutcome.Cancelled, s.tick(5.1))
        assertTrue(!s.active)
    }
}
