package cl.magnesense.detector

/** Mide la frecuencia de muestreo (Hz) en ventanas de [windowSeconds]. */
class RateMeter(private val windowSeconds: Double = 1.0) {
    private var windowStart = Double.NaN
    private var count = 0

    var rateHz: Double = 0.0
        private set

    fun tick(t: Double) {
        if (windowStart.isNaN() || t < windowStart) {
            windowStart = t
            count = 0
        }
        count++
        val span = t - windowStart
        if (span >= windowSeconds) {
            rateHz = (count - 1) / span
            windowStart = t
            count = 1
        }
    }

    fun reset() {
        windowStart = Double.NaN
        count = 0
        rateHz = 0.0
    }
}
