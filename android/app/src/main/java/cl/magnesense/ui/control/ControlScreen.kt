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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cl.magnesense.actions.Device
import cl.magnesense.detector.DetectorState
import cl.magnesense.detector.DetectorStatus
import cl.magnesense.engine.AccessController
import cl.magnesense.engine.Engine
import cl.magnesense.scanning.ScanMode
import cl.magnesense.scanning.ScanState
import cl.magnesense.sensor.SensorHub
import cl.magnesense.sensor.SensorSnapshot
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.ConditionChip
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.SignalMeter
import cl.magnesense.ui.components.StatusPill
import cl.magnesense.ui.theme.Palette

/** Pantalla principal: se lee desde 2 m. La persona no necesita tocarla. */
@Composable
fun ControlScreen(engine: Engine, access: AccessController, onCalibrate: () -> Unit) {
    val d by engine.detector.status.collectAsState()
    val sensors by SensorHub.snapshot.collectAsState()
    val scan by access.scanning.state.collectAsState()
    val devices by access.devices.collectAsState()
    val isOn by access.actions.isOn.collectAsState()
    val last by access.actions.lastResult.collectAsState()

    KeepScreenOn()
    Column(
        Modifier.verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        StatusHeader(d, scan, sensors)
        if (d.state == DetectorState.UNCALIBRATED) {
            Panel {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Antes de usar MagneSense hay que calibrar el imán.", style = MaterialTheme.typography.bodyLarge, color = Palette.Text)
                    BigButton("Calibrar ahora", onCalibrate, Modifier.fillMaxWidth())
                }
            }
        }
        SignalMeter(d.signal, d.onThreshold)
        DeviceGrid(devices, isOn, highlightedId = scan.highlighted?.id, onTap = access::runByTouch)
        ScanProgress(scan)
        last?.let {
            Panel {
                Column {
                    Text("Última acción", style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
                    Text(
                        (if (it.ok) "✓ " else "! ") + it.message,
                        style = MaterialTheme.typography.titleLarge,
                        color = if (it.ok) Palette.Text else Palette.WarningSoft,
                    )
                }
            }
        }
    }
}

@Composable
private fun StatusHeader(d: DetectorStatus, scan: ScanState, sensors: SensorSnapshot) {
    val (text, color) = when {
        !sensors.running -> "Detenido" to Palette.Muted
        d.state == DetectorState.PAUSED -> "En pausa" to Palette.Warning
        d.state == DetectorState.UNCALIBRATED -> "Sin calibrar" to Palette.Warning
        d.state == DetectorState.CALIBRATING_REST || d.state == DetectorState.CALIBRATING_MAGNET -> "Calibrando" to Palette.Muted
        scan.mode == ScanMode.SCANNING -> "Escaneando" to Palette.Highlight
        else -> "Escuchando" to Palette.Ok
    }
    StatusPill(text, color)
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        ConditionChip("Celular quieto", d.gyroOk)
        ConditionChip(
            if (d.saturated) "Imán demasiado cerca" else "Sin metales cerca",
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
    val textColor = if (highlighted) Palette.OnHighlight else Palette.Text
    Column(
        modifier
            .height(170.dp)
            .background(if (highlighted) Palette.Highlight else Palette.Surface, shape)
            .border(if (highlighted) 5.dp else 1.dp, if (highlighted) Palette.Text else Palette.Border, shape)
            .clickable(onClick = onTap)
            .padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(device.icon, fontSize = 48.sp)
        Text(device.name, style = MaterialTheme.typography.titleLarge, color = textColor, textAlign = TextAlign.Center)
        val state = when {
            device.isCaregiver -> "Pide ayuda"
            on -> "● Encendido"
            else -> "○ Apagado"
        }
        Text(state, style = MaterialTheme.typography.bodyMedium, color = if (highlighted) Palette.OnHighlight else Palette.Muted)
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
