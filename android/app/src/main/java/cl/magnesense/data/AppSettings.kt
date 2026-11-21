package cl.magnesense.data

import cl.magnesense.actions.Device
import cl.magnesense.detector.DetectorConfig

/** Todo lo que el cuidador puede configurar. */
data class AppSettings(
    val devices: List<Device> = Device.DEFAULTS,
    val scanStepMs: Long = 2_000,
    /** 0.5 (menos sensible) .. 2.0 (mas sensible). */
    val sensitivity: Double = 1.0,
    val holdMs: Long = 300,
    val caregiverPhone: String = "",
    val caregiverWebhook: String = "",
    /** Base del servidor (p. ej. http://192.168.1.20:8000); vacio = sin telemetria. */
    val serverUrl: String = "",
    val startOnBoot: Boolean = false,
    val voiceEnabled: Boolean = true,
    /** Usar la linterna del celular como "Luz" (demo). Apagada por defecto: parpadea con cada pulso. */
    val phoneTorch: Boolean = false,
    val tuning: DetectionTuning = DetectionTuning(),
    val activationMode: ActivationMode = ActivationMode.PULSES,
    /** Gesto aprendido -> id de dispositivo, [BIND_SCAN], [BIND_SONG], [BIND_QUACK] o [BIND_NONE]. */
    val gestureBindings: Map<String, String> = emptyMap(),
    /** Ya se hizo (o se salto) el asistente de inicio. */
    val setupDone: Boolean = false,
) {
    companion object {
        const val BIND_SCAN = "scan"
        const val BIND_NONE = "none"
        /** Pone o para la cancion (sonido local). Mismo nombre que la accion de server.py. */
        const val BIND_SONG = "play:cancion"
        const val BIND_QUACK = "play:cuack"
    }
}

/** Como se activan las opciones. */
enum class ActivationMode(val label: String, val description: String) {
    PULSES("Pulsos", "Puntos y rayas con el imán: comandos por perfil, Morse o directo. Todo en el celular."),
    SCANNING("Escaneo con un gesto", "Funciona sin internet: un gesto inicia el escaneo y otro elige."),
    GESTURES("Gestos aprendidos", "Cada gesto enseñado hace una acción directa. Todo corre en el celular, sin servidor."),
}

/**
 * Ajuste fino del detector (pantalla Debug). Los valores por defecto son los de [DetectorConfig].
 */
data class DetectionTuning(
    /** Minimo absoluto (µT) que debe superar cada acercamiento al calibrar el iman. */
    val peakMin: Double = DEFAULTS.magnetPeakMin,
    /** ...y en multiplos del ruido σ. Se usa el mayor de los dos. */
    val peakMinSigma: Double = DEFAULTS.magnetPeakMinSigma,
    /** Umbral de activacion en multiplos de σ. */
    val kSigma: Double = DEFAULTS.kSigma,
    /** Umbral de activacion como fraccion del pico calibrado. */
    val peakFraction: Double = DEFAULTS.peakFraction,
    /** Piso del umbral de activacion (µT). */
    val minOn: Double = DEFAULTS.minOnThreshold,
    /** Coseno minimo con la direccion calibrada. */
    val minCosine: Double = DEFAULTS.minCosine,
    /** false = cualquier campo fuerte activa, sin revisar la direccion. */
    val directionCheck: Boolean = DEFAULTS.directionCheck,
    /** true = el iman dado vuelta tambien activa. */
    val acceptReversed: Boolean = DEFAULTS.acceptReversed,
) {
    fun applyTo(c: DetectorConfig) = c.copy(
        magnetPeakMin = peakMin,
        magnetPeakMinSigma = peakMinSigma,
        kSigma = kSigma,
        peakFraction = peakFraction,
        minOnThreshold = minOn,
        minCosine = minCosine,
        directionCheck = directionCheck,
        acceptReversed = acceptReversed,
    )

    private companion object {
        val DEFAULTS = DetectorConfig()
    }
}
