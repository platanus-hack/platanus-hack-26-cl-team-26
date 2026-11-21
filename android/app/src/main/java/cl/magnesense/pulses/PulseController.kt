package cl.magnesense.pulses

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.os.Build
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.KeyEvent
import cl.magnesense.data.HistoryKind
import cl.magnesense.detector.Vec3
import cl.magnesense.feedback.SoundPlayer
import cl.magnesense.feedback.Speaker
import cl.magnesense.sensor.SensorSink
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.util.Locale

/** Como se interpretan las secuencias. */
enum class PulseInterp(val label: String, val description: String) {
    COMMANDS("Comandos", "Cada secuencia hace una acción del perfil."),
    MORSE("Morse", "Escribe letras; \"— — — —\" borra, \"• — • —\" lo dice. Tras 6 s de silencio lo dice solo."),
    DIRECT("Directo", "Cada pulso alterna la luz."),
}

enum class PulseAction { LIGHT, SAY, ALARM, MEDIA, LAP }

data class PulseCommand(val code: String, val action: PulseAction, val text: String, val mediaKey: Int = 0)

/** Que hace cada secuencia en modo comandos, segun el perfil de uso (como en server_pulsos.py). */
enum class PulseProfile(val label: String, val commands: List<PulseCommand>) {
    CARE(
        "Cuidado",
        listOf(
            PulseCommand(".", PulseAction.LIGHT, "Alternar la luz"),
            PulseCommand("-", PulseAction.SAY, "Sí"),
            PulseCommand("..", PulseAction.SAY, "No"),
            PulseCommand("...", PulseAction.ALARM, "Necesito ayuda"),
            PulseCommand("--", PulseAction.SAY, "Tengo dolor"),
            PulseCommand(".-", PulseAction.SAY, "Tengo sed"),
        ),
    ),
    DAILY(
        "Diario",
        listOf(
            PulseCommand(".", PulseAction.LIGHT, "Alternar la luz"),
            PulseCommand("-", PulseAction.MEDIA, "Pausar o reanudar la música", KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE),
            PulseCommand("..", PulseAction.MEDIA, "Canción siguiente", KeyEvent.KEYCODE_MEDIA_NEXT),
            PulseCommand("--", PulseAction.MEDIA, "Canción anterior", KeyEvent.KEYCODE_MEDIA_PREVIOUS),
        ),
    ),
    MOVEMENT(
        "Movimiento",
        listOf(
            PulseCommand(".", PulseAction.LAP, "Marcar vuelta"),
            PulseCommand("-", PulseAction.MEDIA, "Pausar o reanudar la música", KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE),
            PulseCommand("..", PulseAction.MEDIA, "Canción siguiente", KeyEvent.KEYCODE_MEDIA_NEXT),
            PulseCommand("...", PulseAction.ALARM, "Necesito ayuda"),
        ),
    ),
}

data class PulseLast(val code: String, val text: String, val ok: Boolean)

data class PulseUiState(
    val calibrating: Boolean = true,
    val noise: Double = 0.0,
    val phoneMoving: Boolean = false,
    val signal: Double = 0.0,
    val threshold: Double = 1.0,
    val active: Boolean = false,
    /** Duracion del pulso en curso (ms), o 0. */
    val pulseMs: Int = 0,
    val dotMaxMs: Int = 400,
    val letterGapMs: Int = 900,
    /** Tope anti-golpe aprendido (µT), 0 = sin tope. */
    val capUt: Double = 0.0,
    val symbols: String = "",
    val learning: Boolean = false,
    val learnCount: Int = 0,
    val learnTotal: Int = 6,
    val interp: PulseInterp = PulseInterp.COMMANDS,
    val profile: PulseProfile = PulseProfile.CARE,
    val text: String = "",
    val last: PulseLast? = null,
    val log: List<String> = emptyList(),
    val alarm: Boolean = false,
    val lightOn: Boolean = false,
    val said: String = "",
)

/**
 * Modo Pulsos: el iman cerca/lejos se lee como puntos y rayas. Corre en el celular sobre el
 * mismo detector que los gestos aprendidos. Hace las acciones con lo que trae el celular:
 * voz (TTS), sonido y vibracion para la alarma, la linterna como luz y el control de musica.
 */
class PulseController(
    context: Context,
    private val speaker: Speaker,
    private val sounds: SoundPlayer,
    /** Solo actua si el modo elegido es Pulsos y no se esta ensenando un gesto. */
    private val enabled: () -> Boolean,
    private val diag: (String) -> Unit,
    private val history: (HistoryKind, String) -> Unit,
) : SensorSink {

    private val prefs = context.getSharedPreferences("magnesense_pulses", Context.MODE_PRIVATE)
    private val engine = PulseEngine()
    private val lock = Any()
    private val audio = context.getSystemService(AudioManager::class.java)
    private val camera = context.getSystemService(CameraManager::class.java)
    private val torchId: String? = runCatching {
        camera?.cameraIdList?.firstOrNull { camera.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
    }.getOrNull()
    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        context.getSystemService(VibratorManager::class.java)?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Vibrator::class.java)
    }

    private val _state = MutableStateFlow(PulseUiState())
    val state: StateFlow<PulseUiState> = _state.asStateFlow()

    private var tRise = 0.0
    private var tCode: Double? = null
    private var alarmUntil = 0.0
    private var lastPublish = 0.0
    private var wasCalibrating = true
    private val laps = ArrayList<Double>()

    init {
        val interp = runCatching { PulseInterp.valueOf(prefs.getString(KEY_INTERP, "")!!) }.getOrDefault(PulseInterp.COMMANDS)
        val profile = runCatching { PulseProfile.valueOf(prefs.getString(KEY_PROFILE, "")!!) }.getOrDefault(PulseProfile.CARE)
        engine.decoder.dotMax = prefs.getFloat(KEY_DOT, 0.40f).toDouble().coerceIn(0.15, 1.5)
        engine.decoder.letterGap = prefs.getFloat(KEY_GAP, 0.9f).toDouble().coerceIn(0.5, 3.0)
        engine.setCap(prefs.getFloat(KEY_CAP, 0f).toDouble())
        _state.update { it.copy(interp = interp, profile = profile) }
        torchId?.let { id ->
            runCatching {
                camera?.registerTorchCallback(object : CameraManager.TorchCallback() {
                    override fun onTorchModeChanged(cameraId: String, on: Boolean) {
                        if (cameraId == id) _state.update { it.copy(lightOn = on) }
                    }
                }, null)
            }
        }
        publish(0.0)
    }

    // --- Sensores ------------------------------------------------------------

    override fun onMagnetometer(tNanos: Long, value: Vec3) {
        val t = tNanos / NANOS
        val step = synchronized(lock) { engine.step(t, value) }
        if (step.started) tRise = t
        val on = enabled()
        for ((kind, sig) in step.rejected) {
            val text = when (kind) {
                "too_strong" -> "Pulso descartado por golpe: %.1f µT > tope %.1f µT".format(Locale.US, sig, engine.cap)
                "drift" -> "Pulso descartado: cambio lento (deriva), nuevo reposo"
                else -> "Pulso descartado: el imán quedó cerca más de 6 s"
            }
            diag(text)
            if (on && kind == "too_strong") history(HistoryKind.IGNORED, "Descartado: golpe más fuerte que tus pulsos")
        }
        if (on) {
            if (step.started && _state.value.interp == PulseInterp.DIRECT) {
                toggleLight()
                log("Directo: luz ${if (_state.value.lightOn) "encendida" else "apagada"}")
            }
            for (e in step.events) handle(e, t)
            autoSayMorse(t)
        }
        watchCalibration(t)
        if (step.events.isNotEmpty() || step.started || t - lastPublish >= PUBLISH_S) {
            lastPublish = t
            publish(t)
        }
    }

    override fun onGyroscope(tNanos: Long, value: Vec3) {
        synchronized(lock) { engine.gyro(tNanos / NANOS, value) }
    }

    private fun watchCalibration(t: Double) {
        val calibrating = synchronized(lock) { engine.pipeline.calibrating }
        if (wasCalibrating && !calibrating) diag("Pulsos: calibrado, ruido σ = %.3f µT".format(Locale.US, engine.pipeline.noise))
        wasCalibrating = calibrating
    }

    // --- Lo que pide la pantalla --------------------------------------------

    fun recalibrate() {
        synchronized(lock) { engine.recalibrate() }
        diag("Pulsos: recalibrar pedido")
        publish(0.0)
    }

    fun learnTiming() {
        synchronized(lock) { engine.startTiming() }
        speaker.speak("Haz tres pulsos cortos y después tres largos")
        log("Aprendiendo tu ritmo: 3 cortos y 3 largos")
        publish(0.0)
    }

    fun setInterp(i: PulseInterp) {
        prefs.edit().putString(KEY_INTERP, i.name).apply()
        synchronized(lock) { engine.decoder.reset() }
        tCode = null
        _state.update { it.copy(interp = i, text = "", last = null) }
    }

    fun setProfile(p: PulseProfile) {
        prefs.edit().putString(KEY_PROFILE, p.name).apply()
        laps.clear()
        synchronized(lock) { engine.decoder.reset() }
        _state.update { it.copy(profile = p, last = null) }
    }

    fun clearText() {
        tCode = null
        _state.update { it.copy(text = "") }
    }

    fun sayText() = sayMorse()

    // --- Interpretacion ------------------------------------------------------

    private fun handle(e: PulseEvent, t: Double) {
        when (e) {
            is PulseEvent.Pulse -> {
                if (e.sym == '-') sounds.beep(660.0, 200) else sounds.beep(880.0, 70)
                diag("Pulso %s de %d ms".format(Locale.US, if (e.sym == '?') "(ritmo)" else e.sym.toString(), (e.dur * 1000).toInt()))
            }
            is PulseEvent.Timing -> {
                if (e.ok) {
                    prefs.edit()
                        .putFloat(KEY_DOT, engine.decoder.dotMax.toFloat())
                        .putFloat(KEY_GAP, engine.decoder.letterGap.toFloat())
                        .putFloat(KEY_CAP, engine.cap.toFloat())
                        .apply()
                    sounds.beep(1040.0, 260)
                    val msg = "Ritmo aprendido: corto %d ms, largo %d ms. Límite %d ms".format(
                        Locale.US, (e.short * 1000).toInt(), (e.long * 1000).toInt(), (e.dotMax * 1000).toInt(),
                    )
                    log(msg)
                    speaker.speak("Ritmo aprendido")
                } else {
                    sounds.beep(200.0, 260)
                    log("Ritmo no aprendido: cortos y largos muy parecidos. Prueba con largos más largos")
                    speaker.speak("No noté diferencia entre cortos y largos")
                }
            }
            PulseEvent.Space -> {
                if (_state.value.interp == PulseInterp.MORSE) {
                    _state.update { s -> if (s.text.isNotEmpty() && !s.text.endsWith(" ")) s.copy(text = s.text + " ") else s }
                }
            }
            is PulseEvent.Code -> onCode(e, t)
        }
    }

    private fun onCode(e: PulseEvent.Code, t: Double) {
        tCode = t
        val pretty = PulseDecoder.pretty(e.code)
        when (_state.value.interp) {
            PulseInterp.COMMANDS -> {
                val cmd = _state.value.profile.commands.firstOrNull { it.code == e.code }
                _state.update { it.copy(last = PulseLast(pretty, cmd?.text ?: "sin comando asignado", cmd != null)) }
                log("$pretty   ${cmd?.text ?: "sin comando asignado"}")
                if (cmd != null) run(cmd, t) else sounds.beep(200.0, 260)
            }
            PulseInterp.MORSE -> when {
                e.code == "----" -> _state.update { it.copy(text = it.text.dropLast(1), last = PulseLast(pretty, "borrar", true)) }
                e.code == ".-.-" -> {
                    _state.update { it.copy(last = PulseLast(pretty, "decir", true)) }
                    sayMorse()
                }
                e.letter != null -> _state.update { it.copy(text = it.text + e.letter, last = PulseLast(pretty, e.letter, true)) }
                else -> {
                    _state.update { it.copy(last = PulseLast(pretty, "no es una letra", false)) }
                    sounds.beep(200.0, 260)
                }
            }
            PulseInterp.DIRECT -> Unit
        }
        diag("Secuencia $pretty (${e.code}) → ${_state.value.last?.text ?: "-"}")
    }

    private fun run(cmd: PulseCommand, t: Double) {
        when (cmd.action) {
            PulseAction.LIGHT -> toggleLight()
            PulseAction.SAY -> say(cmd.text)
            PulseAction.ALARM -> {
                alarmUntil = t + ALARM_S
                say(cmd.text)
                sounds.alarm(ALARM_SOUND_S)
                vibrate(longArrayOf(0, 500, 200, 500, 200, 500, 200, 500))
                history(HistoryKind.WARNING, "Alarma: ${cmd.text}")
            }
            PulseAction.MEDIA -> media(cmd.mediaKey)
            PulseAction.LAP -> {
                if (laps.isEmpty()) say("Cronómetro iniciado") else say("Vuelta ${laps.size}: ${duration(t - laps.last())}")
                laps += t
            }
        }
        history(HistoryKind.ACTION, "Pulsos: ${cmd.text}")
    }

    private fun autoSayMorse(t: Double) {
        val s = _state.value
        val code = tCode ?: return
        if (s.interp != PulseInterp.MORSE || s.text.isBlank() || engine.active || engine.decoder.symbols.isNotEmpty()) return
        if (t - code >= SPEAK_GAP_S) sayMorse()
    }

    private fun sayMorse() {
        val text = _state.value.text.trim()
        tCode = null
        _state.update { it.copy(text = "") }
        if (text.isNotEmpty()) say(text)
    }

    private fun say(text: String) {
        speaker.speak(text)
        _state.update { it.copy(said = text) }
        log("dijo: $text")
    }

    private fun toggleLight() {
        val id = torchId
        if (id == null) {
            log("Este celular no tiene linterna")
            return
        }
        val on = !_state.value.lightOn
        runCatching { camera?.setTorchMode(id, on) }
            .onSuccess { _state.update { it.copy(lightOn = on) } }
            .onFailure { log("No se pudo usar la linterna: ${it.message}") }
    }

    private fun media(key: Int) {
        val am = audio ?: return
        runCatching {
            am.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, key))
            am.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, key))
        }.onFailure { log("No se pudo controlar la música: ${it.message}") }
    }

    private fun vibrate(pattern: LongArray) {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        runCatching { v.vibrate(VibrationEffect.createWaveform(pattern, -1)) }
    }

    private fun log(msg: String) {
        diag("Pulsos: $msg")
        _state.update { it.copy(log = (listOf(msg) + it.log).take(LOG_LINES)) }
    }

    private fun publish(t: Double) {
        val now = if (t > 0) t else SystemClock.elapsedRealtimeNanos() / NANOS
        synchronized(lock) {
            val p = engine.pipeline
            val d = engine.decoder
            _state.update {
                it.copy(
                    calibrating = p.calibrating,
                    noise = p.noise,
                    phoneMoving = p.phoneMoving(now),
                    signal = engine.signal,
                    threshold = engine.threshold,
                    active = engine.active,
                    pulseMs = if (engine.active) ((now - tRise) * 1000).toInt().coerceAtLeast(0) else 0,
                    dotMaxMs = (d.dotMax * 1000).toInt(),
                    letterGapMs = (d.letterGap * 1000).toInt(),
                    capUt = engine.cap,
                    symbols = d.symbols,
                    learning = d.learning,
                    learnCount = d.learnedCount,
                    learnTotal = d.learnTotal.coerceAtLeast(1),
                    alarm = now < alarmUntil,
                )
            }
        }
    }

    private companion object {
        const val NANOS = 1e9
        const val PUBLISH_S = 0.05
        const val SPEAK_GAP_S = 6.0
        const val ALARM_S = 6.0
        const val ALARM_SOUND_S = 3.0
        const val LOG_LINES = 8
        const val KEY_INTERP = "interp"
        const val KEY_PROFILE = "profile"
        const val KEY_DOT = "dotMax"
        const val KEY_GAP = "letterGap"
        const val KEY_CAP = "cap"

        fun duration(sec: Double): String {
            val m = (sec / 60).toInt()
            val s = Math.round(sec % 60).toInt()
            val min = if (m > 0) "$m minuto${if (m != 1) "s" else ""} " else ""
            return "$min$s segundo${if (s != 1) "s" else ""}"
        }
    }
}
