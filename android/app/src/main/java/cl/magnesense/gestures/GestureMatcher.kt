package cl.magnesense.gestures

import cl.magnesense.remote.DetectorType
import cl.magnesense.remote.RemoteDetector
import cl.magnesense.remote.ServerEvent

/**
 * Decide si un evento de un detector aprendido "dispara" su accion.
 *
 * Copia la regla del servidor (detectors.py, Bank._action), porque la app le pide al
 * servidor action = "none" y ejecuta ella misma la accion. La regla de cada detector
 * (trigger) la guarda el servidor, asi hay una sola fuente de verdad.
 */
object GestureMatcher {

    const val TRIGGER_ANY = "any"
    val EVENT_TRIGGERS = listOf(TRIGGER_ANY, "short", "long", "double")

    fun fires(detector: RemoteDetector, event: ServerEvent): Boolean {
        if (event.detector != detector.name) return false
        return when (detector.type) {
            DetectorType.EVENT -> {
                val trigger = detector.trigger.ifBlank { TRIGGER_ANY }
                event.kind == trigger || (trigger == TRIGGER_ANY && event.kind == "start")
            }
            DetectorType.RHYTHM -> event.kind == "pause"
            DetectorType.STATE ->
                event.kind == "state" && (detector.trigger.isBlank() || event.state == detector.trigger)
        }
    }

    /** Texto simple para la regla de un detector de eventos. */
    fun triggerLabel(trigger: String): String = when (trigger) {
        "short" -> "corto"
        "long" -> "largo"
        "double" -> "doble"
        else -> "cualquiera"
    }
}
