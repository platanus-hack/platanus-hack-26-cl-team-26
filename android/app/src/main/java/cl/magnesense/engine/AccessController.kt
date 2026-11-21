package cl.magnesense.engine

import android.os.SystemClock
import cl.magnesense.actions.ActionResult
import cl.magnesense.actions.Device
import cl.magnesense.actions.DeviceActions
import cl.magnesense.detector.DetectorEvent
import cl.magnesense.detector.EventType
import cl.magnesense.feedback.Haptics
import cl.magnesense.feedback.Speaker
import cl.magnesense.scanning.FeedbackKind
import cl.magnesense.scanning.ScanListener
import cl.magnesense.scanning.ScanOption
import cl.magnesense.scanning.ScanningController
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Une detector -> escaneo -> acciones, con voz y vibracion.
 * Una activacion del iman arma o elige; si el celular se mueve, el escaneo se detiene.
 */
class AccessController(
    private val scope: CoroutineScope,
    detectorEvents: SharedFlow<DetectorEvent>,
    val actions: DeviceActions,
    private val speaker: Speaker,
    private val haptics: Haptics,
) : ScanListener {

    val scanning = ScanningController(this)

    private val _devices = MutableStateFlow(Device.DEFAULTS)
    val devices: StateFlow<List<Device>> = _devices.asStateFlow()

    /** Opciones elegidas (por iman o por toque), para el historial y la telemetria. */
    private val _selections = MutableSharedFlow<Pair<Device, ActionResult>>(extraBufferCapacity = 16)
    val selections: SharedFlow<Pair<Device, ActionResult>> = _selections.asSharedFlow()

    init {
        scanning.setOptions(_devices.value.map { it.toScanOption() })
        scope.launch { detectorEvents.collect(::onDetectorEvent) }
        scope.launch {
            while (isActive) {
                scanning.tick(SystemClock.elapsedRealtime())
                delay(TICK_MS)
            }
        }
    }

    fun setDevices(list: List<Device>) {
        _devices.value = list
        scanning.setOptions(list.map { it.toScanOption() })
    }

    /** El cuidador toca un mosaico: ejecuta directo, sin escaneo. */
    fun runByTouch(device: Device) = execute(device)

    private fun onDetectorEvent(e: DetectorEvent) {
        when (e.type) {
            EventType.ACTIVATED -> scanning.onActivation(SystemClock.elapsedRealtime())
            EventType.PAUSED -> scanning.stop()
            else -> Unit
        }
    }

    override fun speak(text: String, queue: Boolean) = speaker.speak(text, queue)

    override fun feedback(kind: FeedbackKind) = haptics.play(kind)

    override fun onSelected(option: ScanOption) {
        _devices.value.firstOrNull { it.id == option.id }?.let(::execute)
    }

    private fun execute(device: Device) {
        scope.launch {
            val result = actions.run(device)
            speaker.speak(result.message, queue = true)
            if (!result.ok) haptics.play(FeedbackKind.CANCELLED)
            _selections.tryEmit(device to result)
        }
    }

    private companion object {
        const val TICK_MS = 50L
    }
}
