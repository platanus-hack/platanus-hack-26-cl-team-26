package cl.magnesense.tracking

import cl.magnesense.detector.Vec3
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sqrt

enum class TrackState { NO_BASE, NO_MAGNET, FAR, TRACKING }

/** Posicion en cm, ejes del telefono: x a la derecha, y hacia arriba de la pantalla, z saliendo de ella. */
data class TrackPoint(val x: Double, val y: Double, val z: Double)

data class TrackResult(
    val state: TrackState,
    val point: TrackPoint? = null,
    val distCm: Double = 0.0,
    /** 1 = el modelo de dipolo explica todo el campo medido. */
    val confidence: Double = 0.0,
    val fieldUt: Double = 0.0,
)

data class MagnetCalibration(val momentAm2: Double, val tiltDegrees: Double, val fieldUt: Double)

/** Un paso de calibracion que no se pudo hacer; el mensaje se muestra tal cual. */
class TrackerException(message: String) : Exception(message)

/**
 * Posicion 3D del iman respecto al magnetometro. Port de localize.py (servidor).
 *
 * El iman es un dipolo m en p; el campo en el sensor es B = K (3(m·r̂)r̂ − m)/|r|³ con r = −p.
 * Con un solo magnetometro hay 3 mediciones: se fija la orientacion del iman (debe mirar
 * siempre hacia el mismo lado) y se calcula la posicion. Pasos:
 *  1. sin iman cerca: base = campo de la Tierra y del telefono;
 *  2. iman a una distancia conocida sobre el sensor (0, 0, d): se despeja m (B es lineal en m);
 *  3. en vivo: Gauss-Newton amortiguado (Levenberg-Marquardt) desde la posicion anterior.
 * p y −p dan el mismo campo: se elige la mas cercana a la anterior.
 *
 * Kotlin puro (sin Android) para probarlo con un iman simulado. Metodos sincronizados:
 * los sensores llegan en un hilo y la calibracion desde la interfaz.
 */
class MagnetTracker {

    private val recent = ArrayDeque<Vec3>()
    private val trailBuf = ArrayDeque<TrackPoint>()
    private var base: Vec3? = null
    private var noise = 0.2
    private var m: Vec3? = null
    private var p: Vec3? = null

    var refCm: Double? = null
        private set
    var last = TrackResult(TrackState.NO_BASE)
        private set

    val hasBase: Boolean @Synchronized get() = base != null
    val isCalibrated: Boolean @Synchronized get() = m != null

    @Synchronized
    fun trail(): List<TrackPoint> = trailBuf.toList()

    @Synchronized
    fun reset() {
        recent.clear()
        trailBuf.clear()
        base = null
        noise = 0.2
        m = null
        p = null
        refCm = null
        last = TrackResult(TrackState.NO_BASE)
    }

    /** Recibe el vector suavizado del magnetometro (µT). */
    @Synchronized
    fun push(v: Vec3) {
        recent.addLast(v)
        while (recent.size > RECENT) recent.removeFirst()
    }

    // --- Calibracion ----------------------------------------------------------

    /** Paso 1: el iman lejos (> 30 cm). Devuelve el campo base (µT). */
    @Synchronized
    fun setBase(): Vec3 {
        val (mean, spread) = meanRecent()
        base = mean
        noise = max(spread, 0.05)
        m = null
        p = null
        trailBuf.clear()
        last = TrackResult(TrackState.NO_MAGNET)
        return mean
    }

    /** Paso 2: iman a [distCm] justo sobre el sensor, mirando como se va a usar. */
    @Synchronized
    fun calibrate(distCm: Double): MagnetCalibration {
        val b0 = base ?: throw TrackerException("Primero mide sin imán (paso 1).")
        if (distCm !in 1.0..15.0) throw TrackerException("La distancia de calibración debe estar entre 1 y 15 cm.")
        val b = meanRecent().first - b0
        if (b.norm < 3.0) {
            throw TrackerException(
                "El imán casi no cambia el campo (%.1f µT): acércalo justo sobre el punto del sensor.".format(b.norm),
            )
        }
        val pRef = Vec3(0.0, 0.0, distCm / 100)
        val moment = dipoleMatrix(pRef).solve(b)
        m = moment
        refCm = distCm
        p = pRef
        trailBuf.clear()
        last = TrackResult(TrackState.TRACKING)
        val strength = moment.norm
        val tilt = Math.toDegrees(acos((abs(moment.z) / max(strength, 1e-12)).coerceAtMost(1.0)))
        return MagnetCalibration(strength, tilt, b.norm)
    }

    /** Promedio de las ultimas lecturas y su dispersion; exige que esten quietas. */
    private fun meanRecent(n: Int = 15): Pair<Vec3, Double> {
        if (recent.size < n) throw TrackerException("Faltan datos del teléfono: espera un momento a que lleguen lecturas.")
        val arr = recent.toList().takeLast(n)
        var sum = Vec3.ZERO
        for (v in arr) sum += v
        val mean = sum / n.toDouble()
        var vx = 0.0
        var vy = 0.0
        var vz = 0.0
        for (v in arr) {
            val d = v - mean
            vx += d.x * d.x
            vy += d.y * d.y
            vz += d.z * d.z
        }
        val spread = sqrt(vx / n + vy / n + vz / n)
        if (spread > max(1.0, 0.02 * mean.norm)) {
            throw TrackerException(
                "Las lecturas se están moviendo (%.1f µT): deja el imán y el celular quietos un segundo y vuelve a intentar.".format(spread),
            )
        }
        return mean to spread
    }

    // --- En vivo ---------------------------------------------------------------

    @Synchronized
    fun update(): TrackResult {
        val b0 = base ?: return TrackResult(TrackState.NO_BASE).also { last = it }
        val moment = m ?: return TrackResult(TrackState.NO_MAGNET).also { last = it }
        val latest = recent.lastOrNull() ?: return last
        val b = latest - b0
        val bmag = b.norm
        if (bmag < max(10 * noise, 1.5)) {
            last = TrackResult(TrackState.FAR, fieldUt = bmag)
            return last
        }
        val prev = p ?: run {
            // Distancia sobre el eje que explica la intensidad; del lado de la pantalla.
            val d = (2 * K * moment.norm / bmag).pow(1.0 / 3)
            Vec3(0.0, 0.0, min(max(d, MIN_DIST), MAX_DIST))
        }
        var (pos, rel) = solvePosition(b, moment, prev)
        val flipped = pos * -1.0
        if ((flipped - prev).norm < (pos - prev).norm) pos = flipped
        if (pos.norm > MAX_DIST) {
            last = TrackResult(TrackState.FAR, fieldUt = bmag)
            return last
        }
        p = pos
        val point = TrackPoint(pos.x * 100, pos.y * 100, pos.z * 100)
        trailBuf.addLast(point)
        while (trailBuf.size > TRAIL) trailBuf.removeFirst()
        last = TrackResult(
            state = TrackState.TRACKING,
            point = point,
            distCm = pos.norm * 100,
            confidence = max(0.0, 1.0 - 5 * rel),
            fieldUt = bmag,
        )
        return last
    }

    companion object {
        /** µ0/4π en µT·m/(A·m²). */
        const val K = 1e-7 * 1e6
        /** m; mas cerca el modelo de dipolo ya no sirve. */
        const val MIN_DIST = 0.008
        const val MAX_DIST = 0.25
        private const val RECENT = 40
        private const val TRAIL = 60

        /** G(p) tal que B = G(p)·m (µT, p en metros, m en A·m²). */
        fun dipoleMatrix(p: Vec3): Mat3 {
            val r = p * -1.0
            val d = r.norm
            val rh = r / d
            return (Mat3.outer(rh, rh) * 3.0 + Mat3.IDENTITY * -1.0) * (K / (d * d * d))
        }

        fun field(p: Vec3, m: Vec3): Vec3 = dipoleMatrix(p) * m

        /** Posicion que mejor explica el campo [b]. Devuelve (p, error relativo). */
        fun solvePosition(b: Vec3, m: Vec3, p0: Vec3, iters: Int = 25): Pair<Vec3, Double> {
            var p = p0
            var lam = 1e-3
            var err = (field(p, m) - b).norm
            val h = 1e-6
            repeat(iters) {
                val r = field(p, m) - b
                val cols = Array(3) { k ->
                    val e = when (k) {
                        0 -> Vec3(h, 0.0, 0.0)
                        1 -> Vec3(0.0, h, 0.0)
                        else -> Vec3(0.0, 0.0, h)
                    }
                    (field(p + e, m) - field(p - e, m)) / (2 * h)
                }
                val j = Mat3.fromColumns(cols[0], cols[1], cols[2])
                val jt = j.transpose()
                val a = jt * j
                val damping = Mat3.diag(a.diagonal() + Vec3(1e-12, 1e-12, 1e-12)) * lam
                val step = try {
                    (a + damping).solve(jt * r * -1.0)
                } catch (_: ArithmeticException) {
                    return p to err / max(b.norm, 1e-9)
                }
                var cand = p + step
                val dist = cand.norm
                if (dist < MIN_DIST) cand *= MIN_DIST / dist
                val newErr = (field(cand, m) - b).norm
                if (newErr < err) {
                    p = cand
                    err = newErr
                    lam = max(lam / 3, 1e-7)
                    if (step.norm < 1e-7) return p to err / max(b.norm, 1e-9)
                } else {
                    lam *= 4
                }
            }
            return p to err / max(b.norm, 1e-9)
        }
    }
}
