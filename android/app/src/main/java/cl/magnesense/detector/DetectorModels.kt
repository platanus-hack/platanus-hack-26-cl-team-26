package cl.magnesense.detector

enum class DetectorState {
    UNCALIBRATED,
    CALIBRATING_REST,
    CALIBRATING_MAGNET,
    REST,
    CANDIDATE,
    ACTIVE,
    REFRACTORY,
    PAUSED,
}

enum class EventType {
    /** El iman se mantuvo cerca, en la direccion correcta, el tiempo minimo. */
    ACTIVATED,

    /** Campo fuerte pero en otra direccion (otro objeto metalico, otro iman). */
    IGNORED,
    PAUSED,
    RESUMED,
    SATURATED,
    REST_CALIBRATED,
    CALIBRATION_RESTARTED,
    MAGNET_PEAK,
    MAGNET_CALIBRATED,
    REBASELINED,
}

data class DetectorEvent(
    val type: EventType,
    /** Segundos, en la misma base de tiempo de las muestras. */
    val t: Double,
    val signal: Double = 0.0,
    val cosine: Double = Double.NaN,
)

data class MagnetCalibration(
    val medianPeak: Double,
    /** Vector unitario de (B - base) en el pico. */
    val direction: Vec3,
    /** Coseno medio entre cada pico y la direccion media: 1 = siempre igual. */
    val consistency: Double,
    val peaks: List<Double>,
)

/** Lo que se guarda para no recalibrar cada vez que se abre la app. */
data class Calibration(
    val baseline: Vec3,
    val noise: Double,
    val magnet: MagnetCalibration?,
)

data class DetectorStatus(
    val state: DetectorState = DetectorState.UNCALIBRATED,
    /** |B - base| suavizado (µT). */
    val signal: Double = 0.0,
    /** Coseno con la direccion calibrada, NaN si no hay iman calibrado. */
    val cosine: Double = Double.NaN,
    val onThreshold: Double = 0.0,
    val offThreshold: Double = 0.0,
    /** Lo que debe superar cada acercamiento al calibrar el iman (µT). */
    val peakThreshold: Double = 0.0,
    val noise: Double = 0.0,
    val baseline: Vec3? = null,
    val gyroAvailable: Boolean = false,
    val gyroMagnitude: Double = 0.0,
    val gyroOk: Boolean = true,
    val saturated: Boolean = false,
    val sampleRateHz: Double = 0.0,
    /** 0..1 durante la calibracion en reposo o la re-medicion tras una pausa. */
    val progress: Double = 0.0,
    val magnetPeaks: List<Double> = emptyList(),
    val magnet: MagnetCalibration? = null,
    val activations: Int = 0,
    val recentEvents: List<DetectorEvent> = emptyList(),
) {
    val isCalibrated: Boolean get() = baseline != null && magnet != null
}
