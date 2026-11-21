package cl.magnesense.remote

/** Tipos de detector que arma el servidor (detectors.py). */
enum class DetectorType(val wire: String, val label: String, val description: String) {
    EVENT("event", "Movimiento breve", "Un gesto corto, como acercar y alejar el dedo."),
    STATE("state", "Posición que se mantiene", "Dos o más posiciones; cambia cuando pasas de una a otra."),
    RHYTHM("rhythm", "Movimiento repetido", "Algo que se repite, como la respiración; avisa cuando se detiene.");

    companion object {
        fun fromWire(s: String?): DetectorType? = entries.firstOrNull { it.wire == s }
    }
}

/** Un detector aprendido en el servidor, tal como lo informa GET /detectors. */
data class RemoteDetector(
    val name: String,
    val type: DetectorType,
    /** Regla de disparo: any | short | long | double (event), pause (rhythm) o la etiqueta "encendida" (state). */
    val trigger: String,
    val active: Boolean,
    val count: Int,
    val labels: List<String> = emptyList(),
    val state: String? = null,
)

/** Estado de la fase 2 del servidor (bank.status()). */
data class ServerPhase2(
    val calibrating: Boolean = false,
    val noise: Double = 0.0,
    val gyro: Boolean = false,
    val phoneMoving: Boolean = false,
    val detectors: List<RemoteDetector> = emptyList(),
)

data class ServerState(
    /** Hay un WebSocket abierto y llegan mensajes recientes. */
    val connected: Boolean = false,
    val phase2: ServerPhase2 = ServerPhase2(),
    /** Etiqueta que se esta grabando, o "". */
    val recording: String = "",
    /** Ejemplos grabados por etiqueta. */
    val examples: Map<String, Int> = emptyMap(),
    val error: String? = null,
)

/** Un evento de un detector aprendido (una entrada de "events2"). */
data class ServerEvent(
    val detector: String,
    /** start | end | short | long | double | drift | stuck | rhythm_start | pause | resume | state */
    val kind: String,
    val t: Double,
    /** Solo para detectores de estado. */
    val state: String? = null,
    val duration: Double? = null,
)

/** Lo que se pide al crear un detector (cuerpo de POST /train). */
data class TrainRequest(
    val type: DetectorType,
    val name: String,
    /** event: etiqueta de los ejemplos. */
    val label: String? = null,
    /** state: etiquetas a distinguir. */
    val labels: List<String> = emptyList(),
    val trigger: String? = null,
)

/** Resultado de POST /train, con la calidad en palabras simples. */
data class TrainResult(
    val ok: Boolean,
    val detector: String = "",
    val error: String? = null,
    /** event: consistencia (0..1, bueno >= 0,8). */
    val consistency: Double? = null,
    /** state: separacion (bueno > 2). */
    val separation: Double? = null,
) {
    val good: Boolean
        get() = when {
            consistency != null -> consistency >= GOOD_CONSISTENCY
            separation != null -> separation > GOOD_SEPARATION
            else -> ok
        }

    companion object {
        const val GOOD_CONSISTENCY = 0.8
        const val GOOD_SEPARATION = 2.0
    }
}
