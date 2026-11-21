package cl.magnesense.scanning

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class ScanOption(
    val id: String,
    val label: String,
    /** Las opciones criticas piden confirmacion antes de ejecutarse. */
    val critical: Boolean = false,
    val confirmPrompt: String = "¿$label?",
)

enum class ScanMode { IDLE, SCANNING, CONFIRMING }

enum class FeedbackKind { ARMED, SELECTED, CANCELLED }

data class ScanState(
    val mode: ScanMode = ScanMode.IDLE,
    val options: List<ScanOption> = emptyList(),
    /** Opcion resaltada mientras se escanea, -1 si ninguna. */
    val index: Int = -1,
    /** Avance dentro del paso actual (0..1). */
    val stepProgress: Float = 0f,
    val pending: ScanOption? = null,
    /** 0 = "Si", 1 = "No" durante la confirmacion. */
    val confirmIndex: Int = 0,
    val confirmChoices: List<String> = CONFIRM_CHOICES,
    val confirmSecondsLeft: Int = 0,
) {
    val highlighted: ScanOption? get() = options.getOrNull(index).takeIf { mode == ScanMode.SCANNING }

    companion object {
        val CONFIRM_CHOICES = listOf("Sí, llamar", "No, cancelar")
    }
}

/** Efectos que produce el escaneo; los implementa la capa Android. */
interface ScanListener {
    fun speak(text: String, queue: Boolean = false)
    fun feedback(kind: FeedbackKind)
    fun onSelected(option: ScanOption)
}

/**
 * Acceso por un solo interruptor: la primera activacion "arma" el escaneo, luego se resalta
 * (y se dice en voz alta) una opcion cada [stepMs]; otra activacion elige la resaltada.
 * Las opciones criticas se confirman con "Si / No" y se cancelan solas tras [confirmTimeoutMs].
 *
 * No usa relojes propios: el llamador pasa el tiempo (ms), asi se prueba sin esperas.
 */
class ScanningController(
    private val listener: ScanListener,
    options: List<ScanOption> = emptyList(),
    stepMs: Long = 2_000,
    private val idleRounds: Int = 2,
    private val confirmTimeoutMs: Long = 10_000,
    /** Tiempo extra en la primera opcion de la confirmacion, para que alcance a oirse la pregunta. */
    private val confirmPromptMs: Long = 1_500,
) {
    private val _state = MutableStateFlow(ScanState(options = options))
    val state: StateFlow<ScanState> = _state.asStateFlow()

    @Volatile
    var stepMs: Long = stepMs
        set(value) {
            field = value.coerceAtLeast(500)
        }

    private var mode = ScanMode.IDLE
    private var options = options
    private var index = -1
    private var rounds = 0
    private var stepStart = 0L
    private var pending: ScanOption? = null
    private var confirmIndex = 0
    private var confirmStart = 0L
    private var lastNow = 0L

    @Synchronized
    fun setOptions(newOptions: List<ScanOption>) {
        if (newOptions == options) return
        options = newOptions
        if (mode != ScanMode.IDLE) stop()
        publish(lastNow)
    }

    /** Una activacion del iman. */
    @Synchronized
    fun onActivation(now: Long) {
        lastNow = now
        when (mode) {
            ScanMode.IDLE -> {
                if (options.isEmpty()) return
                mode = ScanMode.SCANNING
                index = 0
                rounds = 0
                stepStart = now
                listener.feedback(FeedbackKind.ARMED)
                listener.speak(options[0].label)
            }
            ScanMode.SCANNING -> {
                val option = options[index]
                listener.feedback(FeedbackKind.SELECTED)
                if (option.critical) {
                    mode = ScanMode.CONFIRMING
                    pending = option
                    confirmIndex = 0
                    confirmStart = now
                    stepStart = now + confirmPromptMs
                    listener.speak(option.confirmPrompt)
                    listener.speak(ScanState.CONFIRM_CHOICES[0], queue = true)
                } else {
                    reset()
                    listener.onSelected(option)
                }
            }
            ScanMode.CONFIRMING -> {
                val option = pending
                val yes = confirmIndex == 0
                reset()
                if (yes && option != null) {
                    listener.feedback(FeedbackKind.SELECTED)
                    listener.onSelected(option)
                } else {
                    cancelled()
                }
            }
        }
        publish(now)
    }

    /** Avanza el reloj; llamar seguido (p. ej. cada 50 ms). */
    @Synchronized
    fun tick(now: Long) {
        lastNow = now
        when (mode) {
            ScanMode.IDLE -> Unit
            ScanMode.SCANNING -> if (now - stepStart >= stepMs) {
                stepStart = now
                index++
                if (index >= options.size) {
                    index = 0
                    rounds++
                }
                if (rounds >= idleRounds) {
                    reset()
                    listener.speak("Escaneo en pausa")
                } else {
                    listener.speak(options[index].label)
                }
            }
            ScanMode.CONFIRMING -> when {
                now - confirmStart >= confirmTimeoutMs -> {
                    reset()
                    cancelled()
                }
                now - stepStart >= stepMs -> {
                    stepStart = now
                    confirmIndex = 1 - confirmIndex
                    listener.speak(ScanState.CONFIRM_CHOICES[confirmIndex])
                }
            }
        }
        publish(now)
    }

    /** Detiene el escaneo (p. ej. si el celular se movio). Cancela una confirmacion pendiente. */
    @Synchronized
    fun stop() {
        val wasConfirming = mode == ScanMode.CONFIRMING
        reset()
        if (wasConfirming) cancelled()
        publish(lastNow)
    }

    /** El cuidador toca una opcion de la confirmacion en pantalla. */
    @Synchronized
    fun confirmByTouch(yes: Boolean) {
        if (mode != ScanMode.CONFIRMING) return
        confirmIndex = if (yes) 0 else 1
        onActivation(lastNow)
    }

    private fun cancelled() {
        listener.feedback(FeedbackKind.CANCELLED)
        listener.speak("Cancelado")
    }

    private fun reset() {
        mode = ScanMode.IDLE
        index = -1
        rounds = 0
        pending = null
        confirmIndex = 0
    }

    private fun publish(now: Long) {
        val progress = when (mode) {
            ScanMode.IDLE -> 0f
            else -> ((now - stepStart).toFloat() / stepMs).coerceIn(0f, 1f)
        }
        val secondsLeft = if (mode == ScanMode.CONFIRMING) {
            ((confirmTimeoutMs - (now - confirmStart) + 999) / 1000).toInt().coerceAtLeast(0)
        } else {
            0
        }
        _state.value = ScanState(mode, options, index, progress, pending, confirmIndex, ScanState.CONFIRM_CHOICES, secondsLeft)
    }
}
