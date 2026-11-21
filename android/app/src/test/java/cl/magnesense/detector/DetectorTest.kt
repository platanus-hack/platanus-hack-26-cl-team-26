package cl.magnesense.detector

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import kotlin.random.Random

/**
 * Pruebas con datos sinteticos a 100 Hz: campo terrestre + ruido gaussiano + iman.
 */
class DetectorTest {

    private val earth = Vec3(20.0, -5.0, -40.0)
    private val magnetDir = Vec3(1.0, 0.2, 0.0).normalized()

    private lateinit var sim: Sim

    @Before
    fun setUp() {
        sim = Sim(Detector())
    }

    /** Calibra reposo (10 s) e iman (5 acercamientos de 30 µT). */
    private fun calibrate() {
        sim.detector.startRestCalibration()
        sim.run(10.5)
        assertEquals(DetectorState.REST, sim.detector.state)
        assertTrue(sim.detector.startMagnetCalibration())
        repeat(5) {
            sim.run(0.6) { magnetDir * 30.0 }
            sim.run(0.8)
        }
        assertEquals(DetectorState.REST, sim.detector.state)
        val magnet = sim.detector.status.value.magnet
        assertNotNull(magnet)
        assertEquals(30.0, magnet!!.medianPeak, 1.5)
        assertTrue("consistencia ${magnet.consistency}", magnet.consistency > 0.98)
        assertEquals(15.0, sim.detector.onThreshold, 1.0)
        sim.events.clear()
    }

    @Test
    fun heldMagnetActivatesOnce() {
        calibrate()
        sim.run(1.0)
        sim.run(1.0) { magnetDir * 30.0 }
        sim.run(1.0)
        assertEquals(1, sim.count(EventType.ACTIVATED))
        val e = sim.events.first { it.type == EventType.ACTIVATED }
        assertTrue("coseno ${e.cosine}", e.cosine > 0.95)
    }

    @Test
    fun shortSpikeDoesNotActivate() {
        calibrate()
        sim.run(1.0)
        sim.run(0.05) { magnetDir * 30.0 }
        sim.run(2.0)
        assertEquals(0, sim.count(EventType.ACTIVATED))
    }

    @Test
    fun strongFieldFromWrongDirectionIsIgnored() {
        calibrate()
        val wrong = Vec3(-0.3, 0.2, 1.0).normalized()
        sim.run(1.0)
        sim.run(1.5) { wrong * 40.0 }
        sim.run(1.0)
        assertEquals(0, sim.count(EventType.ACTIVATED))
        assertEquals(1, sim.count(EventType.IGNORED))
    }

    @Test
    fun gyroscopeRotationPausesThenResumes() {
        calibrate()
        sim.run(1.0)
        // El celular gira 1 s: el campo terrestre cambia en el marco del telefono.
        val rotated = Vec3(12.0, 8.0, -3.0)
        sim.run(1.0, gyro = Vec3(0.0, 0.0, 1.2)) { rotated * (sim.elapsedInSegment / 1.0) }
        assertEquals(DetectorState.PAUSED, sim.detector.state)
        assertEquals(1, sim.count(EventType.PAUSED))
        // Queda quieto en la nueva orientacion: re-mide la base y sigue.
        sim.run(2.0) { rotated }
        assertEquals(1, sim.count(EventType.RESUMED))
        assertEquals(0, sim.count(EventType.ACTIVATED))
        sim.run(2.0) { rotated }
        assertEquals(0, sim.count(EventType.ACTIVATED))
        // Y el iman funciona sobre la base nueva.
        sim.run(1.0) { rotated + magnetDir * 30.0 }
        assertEquals(1, sim.count(EventType.ACTIVATED))
    }

    @Test
    fun refractoryBlocksDoubleActivation() {
        calibrate()
        sim.run(1.0)
        // Dos acercamientos muy seguidos: el segundo cae en el periodo refractario.
        sim.run(0.5) { magnetDir * 30.0 }
        sim.run(0.1)
        sim.run(0.5) { magnetDir * 30.0 }
        sim.run(0.5)
        assertEquals(1, sim.count(EventType.ACTIVATED))
        // Mantener el iman mucho rato tampoco repite.
        sim.run(1.5)
        sim.run(3.0) { magnetDir * 30.0 }
        sim.run(0.5)
        assertEquals(2, sim.count(EventType.ACTIVATED))
    }

    @Test
    fun slowDriftDoesNotActivate() {
        // Sin calibrar el iman el umbral es el mas bajo (max(6σ, 1 µT)): caso mas exigente.
        sim.detector.startRestCalibration()
        sim.run(10.5)
        val drift = Vec3(0.3, -0.2, 1.0).normalized()
        sim.run(120.0) { drift * (6.0 * sim.elapsedInSegment / 120.0) }
        assertEquals(0, sim.count(EventType.ACTIVATED))
        assertTrue("senal ${sim.detector.status.value.signal}", sim.detector.status.value.signal < 0.6)
    }

    @Test
    fun saturationIsReported() {
        sim.detector.setSensorInfo(maxRange = 200.0, hasGyroscope = true)
        calibrate()
        sim.run(0.5) { Vec3(200.0, 0.0, 0.0) }
        assertEquals(1, sim.count(EventType.SATURATED))
        assertTrue(sim.detector.status.value.saturated)
    }

    @Test
    fun restCalibrationRestartsIfPhoneMoves() {
        sim.detector.startRestCalibration()
        sim.run(5.0)
        sim.run(0.3, gyro = Vec3(1.0, 0.0, 0.0))
        sim.run(5.0)
        assertEquals(DetectorState.CALIBRATING_REST, sim.detector.state)
        sim.run(5.5)
        assertEquals(DetectorState.REST, sim.detector.state)
        assertEquals(1, sim.count(EventType.CALIBRATION_RESTARTED))
    }

    @Test
    fun weakMagnetCalibratesWhenPeakThresholdIsLowered() {
        sim.detector.startRestCalibration()
        sim.run(10.5)
        // Un iman debil (2 µT) no alcanza el minimo por defecto de 3 µT...
        sim.detector.startMagnetCalibration()
        repeat(5) {
            sim.run(0.6) { magnetDir * 2.0 }
            sim.run(0.8)
        }
        assertEquals(DetectorState.CALIBRATING_MAGNET, sim.detector.state)
        // ...pero si se baja el minimo desde la pantalla de depuracion, si.
        sim.detector.config = sim.detector.config.copy(magnetPeakMin = 1.0, magnetPeakMinSigma = 4.0)
        sim.detector.startMagnetCalibration()
        repeat(5) {
            sim.run(0.6) { magnetDir * 2.0 }
            sim.run(0.8)
        }
        assertEquals(DetectorState.REST, sim.detector.state)
        assertEquals(2.0, sim.detector.status.value.magnet!!.medianPeak, 0.3)
    }

    @Test
    fun restNoiseIgnoresBumpsAndSlowDrift() {
        sim.detector.startRestCalibration()
        // Toque en "Empezar" (golpe de 15 µT), deriva lenta y otro golpe a la mitad.
        sim.run(0.3) { Vec3(15.0, 0.0, 0.0) }
        sim.run(4.0) { Vec3(0.0, 0.0, 0.5 * sim.elapsedInSegment) }
        sim.run(0.3) { Vec3(0.0, 10.0, 2.0) }
        sim.run(6.0) { Vec3(0.0, 0.0, 2.0) }
        assertEquals(DetectorState.REST, sim.detector.state)
        val noise = sim.detector.status.value.noise
        // Ruido gaussiano de 0,2 µT por eje, suavizado: σ real ≈ 0,1 µT.
        assertTrue("ruido $noise", noise < 0.3)
        assertTrue("umbral de calibracion ${sim.detector.magnetPeakThreshold}", sim.detector.magnetPeakThreshold <= 3.0)
    }

    @Test
    fun restoredCalibrationRemeasuresBaseline() {
        calibrate()
        val saved = sim.detector.calibration()!!
        val fresh = Sim(Detector())
        fresh.detector.restore(saved.copy(baseline = saved.baseline + Vec3(5.0, 5.0, 5.0)))
        fresh.run(1.0)
        assertEquals(DetectorState.REST, fresh.detector.state)
        fresh.run(1.0) { magnetDir * 30.0 }
        assertEquals(1, fresh.count(EventType.ACTIVATED))
    }

    /** Simulador: magnetometro y giroscopio a 100 Hz con ruido gaussiano determinista. */
    private inner class Sim(val detector: Detector) {
        private val random = Random(42)
        private var t = 1000.0
        var elapsedInSegment = 0.0
            private set
        val events = mutableListOf<DetectorEvent>()

        fun count(type: EventType) = events.count { it.type == type }

        fun run(seconds: Double, gyro: Vec3 = Vec3.ZERO, extra: () -> Vec3 = { Vec3.ZERO }) {
            val n = (seconds * RATE).toInt()
            for (i in 0 until n) {
                elapsedInSegment = i / RATE
                t += 1.0 / RATE
                val w = gyro + noise(0.01)
                events += detector.processGyroscope(t, w)
                events += detector.processMagnetometer(t, earth + extra() + noise(0.2))
            }
        }

        private fun noise(sigma: Double) =
            Vec3(gauss() * sigma, gauss() * sigma, gauss() * sigma)

        private fun gauss(): Double {
            // Box-Muller
            val u = random.nextDouble().coerceAtLeast(1e-12)
            val v = random.nextDouble()
            return kotlin.math.sqrt(-2 * kotlin.math.ln(u)) * kotlin.math.cos(2 * Math.PI * v)
        }
    }

    private companion object {
        const val RATE = 100.0
    }
}
