package cl.magnesense.detector

/**
 * Todos los parametros ajustables del detector. Tiempos en segundos, campos en µT.
 */
data class DetectorConfig(
    /** Suavizado exponencial del vector B. */
    val smoothTau: Double = 0.040,

    // --- Calibracion en reposo ---
    val restCalibrationSeconds: Double = 10.0,
    /** Se descarta el comienzo (el toque en "Empezar" mueve el campo). */
    val restSettleSeconds: Double = 1.0,
    /** Piso del ruido σ (un sensor "perfecto" no debe dejar el umbral en cero). */
    val noiseFloor: Double = 0.05,

    // --- Calibracion del iman ---
    val magnetPeaksRequired: Int = 5,
    /** Un acercamiento cuenta como pico si supera max(k·σ, este valor). */
    val magnetPeakMinSigma: Double = 8.0,
    val magnetPeakMin: Double = 3.0,

    // --- Umbrales: on = max(kSigma·σ, peakFraction·pico mediano, minOn) / sensibilidad ---
    val kSigma: Double = 6.0,
    val peakFraction: Double = 0.5,
    val minOnThreshold: Double = 1.0,
    val offRatio: Double = 0.5,
    /** > 1 baja el umbral (mas sensible), < 1 lo sube. Nunca baja de [minOnThreshold]. */
    val sensitivity: Double = 1.0,

    // --- Direccion ---
    /** cos minimo entre (B - base) y la direccion calibrada. */
    val minCosine: Double = 0.85,
    /** Intervalo minimo entre eventos IGNORED. */
    val ignoredMinInterval: Double = 2.0,

    // --- Activacion ---
    val holdSeconds: Double = 0.300,
    val refractorySeconds: Double = 1.0,
    /** Si la senal queda alta este tiempo, se toma como nueva linea base. */
    val stuckSeconds: Double = 8.0,

    // --- Giroscopio ---
    val gyroLimit: Double = 0.3,
    val stillSecondsToResume: Double = 1.0,
    val rebaselineSeconds: Double = 0.5,

    // --- Deriva lenta ---
    val driftTau: Double = 5.0,

    // --- Saturacion ---
    /** Fraccion del rango maximo del sensor que se considera "pegado al tope". */
    val saturationFraction: Double = 0.95,
    val saturationSeconds: Double = 0.1,
    val saturationWarnInterval: Double = 5.0,

    /** Cuantos eventos recientes se exponen en el estado. */
    val maxRecentEvents: Int = 20,
)
