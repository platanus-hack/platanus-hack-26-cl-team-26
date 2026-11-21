package cl.magnesense.access

/** Acciones seguras sobre el celular entero: nunca tocan un punto arbitrario de la pantalla. */
enum class PhoneAction(val label: String) {
    NEXT("▲ Siguiente"),
    PREVIOUS("▼ Anterior"),
    BACK("◁ Atrás"),
    HOME("⌂ Inicio"),
    OPEN_APP("Volver a MagneSense"),
}

enum class PhoneResult { DONE, NOT_ENABLED, TOO_SOON, FAILED }

/** Quien ejecuta las acciones de verdad (el servicio de accesibilidad). */
fun interface PhoneActuator {
    fun perform(action: PhoneAction): Boolean
}

/**
 * Puerta de las acciones del Modo celular: sin servicio activo no hace nada, y limita a una
 * accion cada [minIntervalMs] para que un rebote del iman no deslice dos videos.
 * Kotlin puro: se prueba sin Android.
 */
class PhoneGate(private val minIntervalMs: Long = 600) {
    private var lastMs = Long.MIN_VALUE / 2

    @Synchronized
    fun perform(action: PhoneAction, nowMs: Long, actuator: PhoneActuator?): PhoneResult {
        if (actuator == null) return PhoneResult.NOT_ENABLED
        if (nowMs - lastMs < minIntervalMs) return PhoneResult.TOO_SOON
        lastMs = nowMs
        return if (actuator.perform(action)) PhoneResult.DONE else PhoneResult.FAILED
    }
}

/** Punto de encuentro entre Pulsos y el servicio de accesibilidad (mismo proceso). */
object PhoneControl {
    @Volatile
    var actuator: PhoneActuator? = null

    val isEnabled: Boolean get() = actuator != null

    private val gate = PhoneGate()

    fun perform(action: PhoneAction): PhoneResult =
        gate.perform(action, System.nanoTime() / 1_000_000, actuator)
}
