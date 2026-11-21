package cl.magnesense.gate

import cl.magnesense.detector.Vec3
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.cos
import kotlin.random.Random

/** Lecturas a 30 Hz (como la pantalla) con ruido de 0,3 µT por eje. */
class MagnetGateTest {

    private val earth = Vec3(20.0, -5.0, -40.0)
    private val random = Random(5)
    private val gate = MagnetGate()
    private var t = 0.0
    private var last = GateState()

    private fun noise() = Vec3(gauss() * 0.3, gauss() * 0.3, gauss() * 0.3)

    private fun gauss(): Double {
        val u = random.nextDouble().coerceAtLeast(1e-12)
        return kotlin.math.sqrt(-2 * kotlin.math.ln(u)) * cos(2 * Math.PI * random.nextDouble())
    }

    private fun run(seconds: Double, gyro: Vec3 = Vec3.ZERO, extra: () -> Vec3 = { Vec3.ZERO }) {
        repeat((seconds * 30).toInt()) {
            t += 1.0 / 30
            last = gate.update(t, earth + extra() + noise(), gyro)
        }
    }

    @Test
    fun noMagnetNeverOpens() {
        run(10.0)
        assertEquals(GatePhase.WAITING, last.phase)
        assertEquals(0.0, last.progress, 1e-9)
    }

    @Test
    fun heldMagnetOpensInAboutThreeSeconds() {
        run(1.0)
        run(1.0) { Vec3(30.0, 10.0, 0.0) }
        assertEquals(GatePhase.CHARGING, last.phase)
        run(1.0) { Vec3(30.0, 10.0, 0.0) }
        assertEquals(GatePhase.CHARGING, last.phase)   // dura ~1 s mas que antes
        run(1.0) { Vec3(30.0, 10.0, 0.0) }
        assertEquals(GatePhase.DONE, last.phase)
        // Una vez abierta queda abierta.
        run(1.0)
        assertEquals(GatePhase.DONE, last.phase)
    }

    @Test
    fun shortSpikeDoesNotOpenAndDrains() {
        run(1.0)
        run(0.3) { Vec3(40.0, 0.0, 0.0) }
        val peak = last.progress
        assertTrue("debe cargar algo: $peak", peak in 0.1..0.5)
        run(1.0)
        assertEquals(GatePhase.WAITING, last.phase)
        assertTrue("debe bajar: ${last.progress}", last.progress < peak)
    }

    @Test
    fun movingThePhoneDoesNotCharge() {
        run(1.0)
        // Girar el telefono cambia el campo de la Tierra visto por el sensor.
        run(2.0, gyro = Vec3(0.0, 0.0, 1.0)) { Vec3(25.0, -10.0, 15.0) }
        assertEquals(0.0, last.progress, 1e-9)
        // Queda quieto en otra orientacion: se mide el fondo de nuevo y no abre.
        run(3.0) { Vec3(25.0, -10.0, 15.0) }
        assertEquals(GatePhase.WAITING, last.phase)
        assertEquals(0.0, last.progress, 1e-9)
    }

    @Test
    fun weakMagnetAlsoOpens() {
        run(1.0)
        run(4.5) { Vec3(0.0, 12.0, 0.0) }   // 12 µT: imán débil o lejano
        assertEquals(GatePhase.DONE, last.phase)
    }
}
