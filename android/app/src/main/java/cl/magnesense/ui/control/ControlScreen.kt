package cl.magnesense.ui.control

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cl.magnesense.MagneSenseApp
import cl.magnesense.actions.Device
import cl.magnesense.data.ActivationMode
import cl.magnesense.data.AppSettings
import cl.magnesense.detector.DetectorState
import cl.magnesense.detector.DetectorStatus
import cl.magnesense.engine.IgnoredNotice
import cl.magnesense.gestures.GestureStatus
import cl.magnesense.scanning.ScanMode
import cl.magnesense.scanning.ScanState
import cl.magnesense.sensor.SensorHub
import cl.magnesense.sensor.SensorSnapshot
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.ConditionChip
import cl.magnesense.ui.components.DeviceBadgeIcon
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.SignalMeter
import cl.magnesense.ui.components.StatusPill
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.delay
import java.util.Locale

/** Pantalla principal: se lee desde 2 m. La persona no necesita tocarla. */
@Composable
fun ControlScreen(app: MagneSenseApp, onCalibrate: () -> Unit, onTeachGesture: () -> Unit) {
    val engine = app.engine
    val access = app.access
    val d by engine.detector.status.collectAsState()
    val gestureStatus by app.gestures.status.collectAsState()
    val settings by app.settings.settings.collectAsState()
    var flashingId by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        app.gestures.fired.collect { f ->
            flashingId = f.deviceId
            delay(FLASH_MS)
            if (flashingId == f.deviceId) flashingId = null
        }
    }
    val sensors by SensorHub.snapshot.collectAsState()
    val scan by access.scanning.state.collectAsState()
    val devices by access.devices.collectAsState()
    val isOn by access.actions.isOn.collectAsState()
    val last by access.actions.lastResult.collectAsState()
    val ignored by access.ignored.collectAsState()

    KeepScreenOn()
    Column(
        Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        StatusHeader(d, scan, sensors, gestureStatus, onRecenter = engine.detector::recenterBaseline)
        if (settings.activationMode == ActivationMode.GESTURES) GestureBindingsRow(settings.gestureBindings, devices)
        BigOutlineButton("● Grabar un gesto nuevo", onTeachGesture, Modifier.fillMaxWidth())
        if (d.state == DetectorState.UNCALIBRATED) {
            Panel {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Antes de usar MagneSense hay que calibrar el imán.", style = MaterialTheme.typography.bodyLarge, color = Palette.Text)
                    BigButton("Calibrar ahora", onCalibrate, Modifier.fillMaxWidth())
                }
            }
        }
        SignalMeter(d.signal, d.onThreshold)
        ignored?.let { IgnoredBanner(it, d.minCosine, onDismiss = access::dismissIgnored) }
        DeviceGrid(devices, isOn, highlightedId = scan.highlighted?.id ?: flashingId, onTap = access::runByTouch)
        ScanProgress(scan)
        last?.let {
            Panel {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("Última acción:", style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
                    Text(
                        (if (it.ok) "✓ " else "! ") + it.message,
                        style = MaterialTheme.typography.titleMedium,
                        color = if (it.ok) Palette.Highlight else Palette.WarningSoft,
                    )
                }
            }
        }
    }
}

@Composable
private fun StatusHeader(
    d: DetectorStatus,
    scan: ScanState,
    sensors: SensorSnapshot,
    gestures: GestureStatus,
    onRecenter: () -> Unit,
) {
    val (text, color) = when {
        !sensors.running -> "Detenido" to Palette.Muted
        gestures.gesturesActive -> "Gestos" to Palette.Ok
        gestures.fallback && d.state != DetectorState.PAUSED -> "Escaneo (sin servidor)" to Palette.Warning
        d.state == DetectorState.PAUSED -> "En pausa" to Palette.Warning
        d.state == DetectorState.UNCALIBRATED -> "Sin calibrar" to Palette.Warning
        d.state == DetectorState.CALIBRATING_REST || d.state == DetectorState.CALIBRATING_MAGNET -> "Calibrando" to Palette.Muted
        scan.mode == ScanMode.SCANNING -> "Escaneando" to Palette.Highlight
        else -> "Escuchando" to Palette.Ok
    }
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusPill(text, color)
        Row(
            Modifier
                .background(Palette.Surface, RoundedCornerShape(50))
                .border(1.dp, Palette.Border, RoundedCornerShape(50))
                .clickable(onClick = onRecenter)
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("⟳ Re-centrar 0 µT", color = Palette.Text, style = MaterialTheme.typography.bodyMedium)
        }
    }
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        ConditionChip("Quieto", d.gyroOk)
        ConditionChip(
            if (d.saturated) "Saturado" else "Campo limpio",
            !d.saturated && sensors.earthField in EARTH_FIELD_RANGE,
        )
        ConditionChip("Calibrado", d.isCalibrated)
    }
}

@Composable
private fun DeviceGrid(
    devices: List<Device>,
    isOn: Map<String, Boolean>,
    highlightedId: String?,
    onTap: (Device) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        for (row in devices.chunked(2)) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                for (device in row) {
                    DeviceTile(
                        device = device,
                        on = isOn[device.id] == true,
                        highlighted = device.id == highlightedId,
                        onTap = { onTap(device) },
                        modifier = Modifier.weight(1f),
                    )
                }
                if (row.size == 1) Column(Modifier.weight(1f)) {}
            }
        }
    }
}

@Composable
private fun DeviceTile(device: Device, on: Boolean, highlighted: Boolean, onTap: () -> Unit, modifier: Modifier) {
    val shape = RoundedCornerShape(20.dp)
    val bgColor = when {
        highlighted -> Palette.Highlight
        on -> androidx.compose.ui.graphics.Color(0xFF1D283A)
        else -> Palette.Surface
    }
    val borderColor = when {
        highlighted -> Palette.Text
        on -> Palette.Ok
        else -> Palette.Border
    }
    val borderWidth = when {
        highlighted -> 5.dp
        on -> 3.dp
        else -> 1.dp
    }
    val textColor = if (highlighted) Palette.OnHighlight else Palette.Text
    val stateColor = when {
        highlighted -> Palette.OnHighlight
        on -> Palette.Ok
        else -> Palette.Muted
    }
    Column(
        modifier
            .height(144.dp)
            .background(bgColor, shape)
            .border(borderWidth, borderColor, shape)
            .clickable(onClick = onTap)
            .padding(10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterVertically),
    ) {
        DeviceBadgeIcon(icon = device.icon, on = on, highlighted = highlighted)
        Text(device.name, style = MaterialTheme.typography.titleLarge, color = textColor, textAlign = TextAlign.Center)
        val state = when {
            device.isCaregiver -> "Pide ayuda"
            on -> "● ENCENDIDO"
            else -> "○ Apagado"
        }
        Text(state, style = MaterialTheme.typography.labelLarge, color = stateColor)
    }
}

@Composable
private fun ScanProgress(scan: ScanState) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        LinearProgressIndicator(
            progress = { if (scan.mode == ScanMode.SCANNING) scan.stepProgress else 0f },
            modifier = Modifier.fillMaxWidth().height(14.dp),
            color = Palette.Highlight,
            trackColor = Palette.Border,
            drawStopIndicator = {},
        )
        val text = when (scan.mode) {
            ScanMode.SCANNING -> "Acerca el imán para elegir: ${scan.highlighted?.label ?: ""}"
            ScanMode.CONFIRMING -> "Confirmando…"
            ScanMode.IDLE -> "Acerca el imán para empezar"
        }
        Text(text, style = MaterialTheme.typography.titleMedium, color = Palette.Text)
    }
}

/** Que hace cada gesto aprendido, p. ej. "izquierda → Luz". */
@Composable
private fun GestureBindingsRow(bindings: Map<String, String>, devices: List<Device>) {
    val parts = bindings.mapNotNull { (gesture, target) ->
        when (target) {
            AppSettings.BIND_SCAN -> "$gesture → escaneo"
            AppSettings.BIND_NONE -> null
            else -> devices.firstOrNull { it.id == target }?.let { "$gesture → ${it.name}" }
        }
    }
    Text(
        if (parts.isEmpty()) "Aún no hay gestos enlazados (pestaña Gestos)" else parts.joinToString("   ·   "),
        style = MaterialTheme.typography.titleMedium,
        color = Palette.Text,
    )
}

/** Aviso visible cuando un campo fuerte se descarto por direccion; desaparece solo a los 10 s. */
@Composable
private fun IgnoredBanner(notice: IgnoredNotice, minCosine: Double, onDismiss: () -> Unit) {
    LaunchedEffect(notice) {
        delay(IGNORED_NOTICE_MS)
        onDismiss()
    }
    Panel(Modifier.border(2.dp, Palette.Warning, RoundedCornerShape(16.dp)).clickable(onClick = onDismiss)) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("! Detecté el imán, pero en otra dirección", style = MaterialTheme.typography.titleMedium, color = Palette.WarningSoft)
            Text(
                "cos %.2f (se pide ≥ %.2f). Acércalo como al calibrar, recalibra, o ajusta la dirección en Debug.".format(
                    Locale.US, notice.cosine, minCosine,
                ),
                style = MaterialTheme.typography.bodyMedium,
                color = Palette.Text,
            )
        }
    }
}

/** Mantiene la pantalla encendida mientras se muestra el control. */
@Composable
fun KeepScreenOn() {
    val view = LocalView.current
    DisposableEffect(view) {
        view.keepScreenOn = true
        onDispose { view.keepScreenOn = false }
    }
}

/** Rango razonable del campo terrestre; fuera de el probablemente hay metal o un iman cerca. */
private val EARTH_FIELD_RANGE = 20.0..90.0

private const val IGNORED_NOTICE_MS = 10_000L

/** Cuanto se resalta el mosaico cuando un gesto aprendido lo activa. */
private const val FLASH_MS = 1_000L
