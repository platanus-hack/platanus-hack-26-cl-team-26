package cl.magnesense

import android.app.Application
import cl.magnesense.actions.CaregiverConfig
import cl.magnesense.actions.DeviceActions
import cl.magnesense.data.AppSettings
import cl.magnesense.data.EventLog
import cl.magnesense.data.HistoryKind
import cl.magnesense.data.SettingsStore
import cl.magnesense.detector.DetectorEvent
import cl.magnesense.detector.EventType
import cl.magnesense.engine.AccessController
import cl.magnesense.engine.Engine
import cl.magnesense.feedback.Haptics
import cl.magnesense.feedback.Speaker
import cl.magnesense.sensor.SensorHub
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
    lateinit var engine: Engine
        private set
    lateinit var access: AccessController
        private set
    private lateinit var speaker: Speaker

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)
        history = EventLog(this)
        speaker = Speaker(this)
        engine = Engine()
        settings.loadCalibration()?.let(engine.detector::restore)
        SensorHub.sink = engine
        access = AccessController(
            scope = scope,
            detectorEvents = engine.events,
            actions = DeviceActions(this),
            speaker = speaker,
            haptics = Haptics(this),
        )

        scope.launch { settings.settings.collect(::apply) }
        scope.launch { engine.events.collect(::onDetectorEvent) }
        scope.launch {
            access.selections.collect { (device, result) ->
                history.add(if (result.ok) HistoryKind.ACTION else HistoryKind.ACTION_FAILED, "${device.icon} ${result.message}")
            }
        }
    }

    private fun apply(s: AppSettings) {
        val detector = engine.detector
        detector.config = detector.config.copy(sensitivity = s.sensitivity, holdSeconds = s.holdMs / 1000.0)
        access.scanning.stepMs = s.scanStepMs
        access.setDevices(s.devices)
        access.actions.caregiver = CaregiverConfig(s.caregiverPhone.trim(), s.caregiverWebhook.trim())
        speaker.enabled = s.voiceEnabled
    }

    private fun onDetectorEvent(e: DetectorEvent) {
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

    private fun saveCalibration() {
        engine.detector.calibration()?.let(settings::saveCalibration)
    }
}
