package cl.magnesense

import android.app.Application
import cl.magnesense.actions.CaregiverConfig
import cl.magnesense.actions.DeviceActions
import cl.magnesense.data.AppSettings
import cl.magnesense.data.DiagLog
import cl.magnesense.data.EventLog
import cl.magnesense.data.HistoryKind
import cl.magnesense.data.SettingsStore
import cl.magnesense.detector.DetectorEvent
import cl.magnesense.detector.EventType
import cl.magnesense.engine.AccessController
import cl.magnesense.engine.Engine
import cl.magnesense.detector.Vec3
import cl.magnesense.feedback.Haptics
import cl.magnesense.feedback.SoundPlayer
import cl.magnesense.feedback.Speaker
import cl.magnesense.gestures.GestureController
import cl.magnesense.gestures.LocalGestures
import cl.magnesense.pulses.PulseController
import cl.magnesense.data.ActivationMode
import cl.magnesense.remote.ServerApi
import cl.magnesense.remote.ServerSocket
import cl.magnesense.sensor.SensorHub
import cl.magnesense.sensor.SensorSink
import cl.magnesense.telemetry.TelemetryClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.util.Locale

/**
 * Raiz de composicion: crea los objetos compartidos por el servicio y la interfaz,
 * aplica los ajustes en vivo y registra el historial.
 */
class MagneSenseApp : Application() {

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    lateinit var settings: SettingsStore
        private set
    lateinit var history: EventLog
        private set
    /** Registro tecnico para buscar errores (se comparte desde Historial). */
    lateinit var diag: DiagLog
        private set
    lateinit var engine: Engine
        private set
    lateinit var access: AccessController
        private set
    lateinit var telemetry: TelemetryClient
        private set
    lateinit var server: ServerSocket
        private set
    lateinit var serverApi: ServerApi
        private set
    lateinit var gestures: GestureController
        private set
    /** Gestos aprendidos que corren en el celular (sin servidor). */
    lateinit var localGestures: LocalGestures
        private set
    lateinit var sounds: SoundPlayer
        private set
    /** Modo Pulsos (por defecto): puntos y rayas con el iman. */
    lateinit var pulses: PulseController
        private set
    lateinit var speaker: Speaker
        private set

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)
        history = EventLog(this)
        diag = DiagLog(this)
        diag.catchCrashes()
        diag.add("App iniciada (v${packageManager.getPackageInfo(packageName, 0).versionName})")
        speaker = Speaker(this)
        engine = Engine()
        telemetry = TelemetryClient(scope)
        localGestures = LocalGestures(this, diag::add, history::add)
        sounds = SoundPlayer()
        pulses = PulseController(
            this,
            speaker,
            sounds,
            enabled = { settings.settings.value.activationMode == ActivationMode.PULSES && !(::gestures.isInitialized && gestures.teaching) },
            torchAllowed = { settings.settings.value.phoneTorch },
            diag = diag::add,
            history = history::add,
        )
        engine.rawListener = Tee(telemetry, localGestures, pulses)
        server = ServerSocket(scope)
        serverApi = ServerApi { settings.settings.value.serverUrl.trim().trimEnd('/') }
        settings.loadCalibration()?.let(engine.detector::restore)
        SensorHub.sink = engine
        access = AccessController(
            scope = scope,
            detectorEvents = engine.events,
            actions = DeviceActions(this),
            speaker = speaker,
            haptics = Haptics(this),
        )

        gestures = GestureController(
            scope = scope,
            source = localGestures.state,
            events = localGestures.events,
            access = access,
            settings = settings.settings,
            speaker = speaker,
            sounds = sounds,
            log = {
                history.add(HistoryKind.ACTIVATION, it)
                diag.add(it)
            },
        )

        scope.launch { settings.settings.collect(::apply) }
        scope.launch { engine.events.collect(::onDetectorEvent) }
        scope.launch {
            access.selections.collect { (device, result) ->
                history.add(if (result.ok) HistoryKind.ACTION else HistoryKind.ACTION_FAILED, result.message)
                diag.add("${if (result.ok) "Acción" else "ERROR en acción"} ${device.name}: ${result.message}")
                telemetry.sendEvent(if (result.ok) "selected" else "action_failed", "${device.name}: ${result.message}")
            }
        }
    }

    private fun apply(s: AppSettings) {
        val detector = engine.detector
        detector.config = s.tuning.applyTo(detector.config)
            .copy(sensitivity = s.sensitivity, holdSeconds = s.holdMs / 1000.0)
        access.scanning.stepMs = s.scanStepMs
        access.setDevices(s.devices)
        access.actions.caregiver = CaregiverConfig(s.caregiverPhone.trim(), s.caregiverWebhook.trim())
        speaker.enabled = s.voiceEnabled
        access.actions.useTorch = s.phoneTorch
        telemetry.baseUrl = s.serverUrl
        server.baseUrl = s.serverUrl
    }

    private fun onDetectorEvent(e: DetectorEvent) {
        forwardToServer(e)
        when (e.type) {
            EventType.ACTIVATED -> history.add(HistoryKind.ACTIVATION, "Imán detectado (%.1f µT)".format(Locale.US, e.signal))
            EventType.IGNORED -> history.add(HistoryKind.IGNORED, "Ignorado: campo en otra dirección")
            EventType.PAUSED -> history.add(HistoryKind.PAUSE, "Pausa: el celular se movió")
            EventType.RESUMED -> history.add(HistoryKind.PAUSE, "Reanudado")
            EventType.SATURATED -> history.add(HistoryKind.WARNING, "Imán demasiado cerca del sensor")
            EventType.MAGNET_CALIBRATED -> {
                history.add(HistoryKind.CALIBRATION, "Calibración lista (pico %.1f µT)".format(Locale.US, e.signal))
                saveCalibration()
            }
            EventType.REST_CALIBRATED, EventType.REBASELINED -> saveCalibration()
            else -> Unit
        }
    }

    private fun forwardToServer(e: DetectorEvent) {
        val text = when (e.type) {
            EventType.ACTIVATED -> "Activación"
            EventType.IGNORED -> "Ignorado (otra dirección)"
            EventType.PAUSED -> "En pausa: el celular se movió"
            EventType.RESUMED -> "Reanudado"
            EventType.SATURATED -> "Sensor saturado"
            EventType.MAGNET_CALIBRATED -> "Imán calibrado"
            else -> return
        }
        telemetry.sendEvent(e.type.name.lowercase(), text, e.signal, e.cosine)
    }

    private fun saveCalibration() {
        engine.detector.calibration()?.let(settings::saveCalibration)
    }
}

/** Reparte cada muestra cruda a varios oyentes (telemetria y gestos aprendidos). */
private class Tee(private vararg val sinks: SensorSink) : SensorSink {
    override fun onSensorsStarted(magMaxRange: Double, gyroAvailable: Boolean) =
        sinks.forEach { it.onSensorsStarted(magMaxRange, gyroAvailable) }

    override fun onMagnetometer(tNanos: Long, value: Vec3) = sinks.forEach { it.onMagnetometer(tNanos, value) }

    override fun onGyroscope(tNanos: Long, value: Vec3) = sinks.forEach { it.onGyroscope(tNanos, value) }
}
