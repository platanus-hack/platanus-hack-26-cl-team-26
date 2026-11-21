package cl.magnesense.access

enum class ScanPhase { IDLE, SWEEP_X, SWEEP_Y, CONFIRM }

/** Lo que se dibuja: posiciones en fraccion de la pantalla (0..1). */
data class ScanFrame(
    val phase: ScanPhase,
    val x: Float = 0f,
    val y: Float = 0f,
    val fixedX: Float? = null,
    val fixedY: Float? = null,
    /** Fraccion del tiempo de confirmacion que queda, 1 → 0 (fase CONFIRM). */
    val confirmFraction: Float = 0f,
)

sealed interface ScanOutcome {
    data object None : ScanOutcome
    data class Tap(val x: Float, val y: Float) : ScanOutcome
    data object Cancelled : ScanOutcome
}

/**
 * Cursor por barrido ("point scan", como Switch Access): con un solo pulso a la vez se elige
 * cualquier punto de la pantalla.
 *  1. Una linea vertical recorre la pantalla de lado a lado: un pulso fija la columna (x).
 *  2. Una linea horizontal recorre de arriba a abajo: un pulso fija la fila (y).
 *  3. Aparece una mira: otro pulso toca ese punto; si no hay pulso, se cancela solo.
 * Las lineas van y vuelven ([maxPasses] pasadas) y luego se cancela. El pulso se toma
 * [latencyS] antes, para compensar lo que la persona tarda en reaccionar.
 *
 * Kotlin puro y sin relojes propios: el llamador pasa el tiempo (s).
 */
class PointScan(
    private val xPassS: Double = 3.5,
    private val yPassS: Double = 5.0,
    private val maxPasses: Int = 4,
    private val confirmS: Double = 4.0,
    private val latencyS: Double = 0.3,
    private val margin: Float = 0.04f,
) {
    var phase = ScanPhase.IDLE
        private set
    private var phaseStart = 0.0
    private var fixedX: Float? = null
    private var fixedY: Float? = null

    val active: Boolean get() = phase != ScanPhase.IDLE

    fun start(t: Double) {
        phase = ScanPhase.SWEEP_X
        phaseStart = t
        fixedX = null
        fixedY = null
    }

    fun cancel() {
        phase = ScanPhase.IDLE
    }

    /** Un pulso del iman: avanza de fase o, en la confirmacion, devuelve el toque. */
    fun pulse(t: Double): ScanOutcome {
        val back = (t - latencyS).coerceAtLeast(phaseStart)
        return when (phase) {
            ScanPhase.IDLE -> ScanOutcome.None
            ScanPhase.SWEEP_X -> {
                fixedX = sweep(back - phaseStart, xPassS).first
                phase = ScanPhase.SWEEP_Y
                phaseStart = t
                ScanOutcome.None
            }
            ScanPhase.SWEEP_Y -> {
                fixedY = sweep(back - phaseStart, yPassS).first
                phase = ScanPhase.CONFIRM
                phaseStart = t
                ScanOutcome.None
            }
            ScanPhase.CONFIRM -> {
                phase = ScanPhase.IDLE
                ScanOutcome.Tap(fixedX ?: 0.5f, fixedY ?: 0.5f)
            }
        }
    }

    /** Avanza el reloj; devuelve Cancelled si se acabaron las pasadas o el tiempo de confirmar. */
    fun tick(t: Double): ScanOutcome {
        val elapsed = t - phaseStart
        val expired = when (phase) {
            ScanPhase.IDLE -> false
            ScanPhase.SWEEP_X -> sweep(elapsed, xPassS).second >= maxPasses
            ScanPhase.SWEEP_Y -> sweep(elapsed, yPassS).second >= maxPasses
            ScanPhase.CONFIRM -> elapsed >= confirmS
        }
        if (!expired) return ScanOutcome.None
        phase = ScanPhase.IDLE
        return ScanOutcome.Cancelled
    }

    fun frame(t: Double): ScanFrame {
        val elapsed = t - phaseStart
        return when (phase) {
            ScanPhase.IDLE -> ScanFrame(ScanPhase.IDLE)
            ScanPhase.SWEEP_X -> ScanFrame(phase, x = sweep(elapsed, xPassS).first)
            ScanPhase.SWEEP_Y -> ScanFrame(phase, x = fixedX ?: 0f, y = sweep(elapsed, yPassS).first, fixedX = fixedX)
            ScanPhase.CONFIRM -> ScanFrame(
                phase,
                x = fixedX ?: 0f,
                y = fixedY ?: 0f,
                fixedX = fixedX,
                fixedY = fixedY,
                confirmFraction = ((confirmS - elapsed) / confirmS).toFloat().coerceIn(0f, 1f),
            )
        }
    }

    /** Posicion de ida y vuelta dentro de los margenes, y cuantas pasadas completas lleva. */
    private fun sweep(elapsed: Double, passS: Double): Pair<Float, Int> {
        val passes = elapsed.coerceAtLeast(0.0) / passS
        val k = passes.toInt()
        val frac = (passes - k).toFloat()
        val along = if (k % 2 == 0) frac else 1f - frac
        return (margin + along * (1f - 2 * margin)) to k
    }
}
