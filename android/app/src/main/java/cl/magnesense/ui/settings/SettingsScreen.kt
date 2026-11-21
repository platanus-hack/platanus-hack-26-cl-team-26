package cl.magnesense.ui.settings

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cl.magnesense.actions.Device
import cl.magnesense.actions.DeviceActions
import cl.magnesense.actions.DeviceKind
import cl.magnesense.data.ActivationMode
import cl.magnesense.data.AppSettings
import cl.magnesense.data.SettingsStore
import cl.magnesense.remote.ServerSocket
import cl.magnesense.telemetry.TelemetryClient
import cl.magnesense.ui.components.AppSlider
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Field
import cl.magnesense.ui.components.DeviceIconCatalog
import cl.magnesense.ui.components.DeviceVectorIcon
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.ScreenColumn
import cl.magnesense.ui.components.SectionTitle
import cl.magnesense.ui.components.Toggle
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.launch
import java.util.Locale

/** Ajustes para el cuidador. Todo se guarda al momento. */
@Composable
fun SettingsScreen(store: SettingsStore, actions: DeviceActions, telemetry: TelemetryClient, server: ServerSocket) {
    val s by store.settings.collectAsState()
    val link by telemetry.status.collectAsState()
    val live by server.state.collectAsState()
    val scope = rememberCoroutineScope()
    var testMessage by remember { mutableStateOf<String?>(null) }

    fun updateDevice(d: Device) = store.update { st -> st.copy(devices = st.devices.map { if (it.id == d.id) d else it }) }

    Column(Modifier.verticalScroll(rememberScrollState())) {
        ScreenColumn {
            Text("Ajustes", style = MaterialTheme.typography.headlineMedium, color = Palette.Text)

            SectionTitle("Dispositivos")
            testMessage?.let { Text(it, style = MaterialTheme.typography.titleMedium, color = Palette.WarningSoft) }
            for (device in s.devices) {
                DeviceEditor(
                    device = device,
                    canDelete = s.devices.size > 1,
                    onChange = ::updateDevice,
                    onDelete = { store.update { st -> st.copy(devices = st.devices.filterNot { it.id == device.id }) } },
                    onTest = { on ->
                        scope.launch {
                            val r = if (device.isCaregiver) actions.callCaregiver(device) else actions.setPower(device, on)
                            testMessage = (if (r.ok) "✓ " else "! ") + r.message
                        }
                    },
                )
            }
            if (s.devices.size < MAX_DEVICES) {
                BigOutlineButton(
                    "Agregar dispositivo",
                    onClick = {
                        store.update { st ->
                            st.copy(devices = st.devices + Device("d${System.currentTimeMillis()}", "Enchufe", "plug"))
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            SectionTitle("Activación")
            Panel { ActivationSettings(s, store, serverConnected = live.connected) }

            SectionTitle("Escaneo y detección")
            Panel { DetectionSettings(s, store) }

            SectionTitle("Cuidador")
            Panel { CaregiverSettings(s, store) }

            SectionTitle("Servidor (panel web)")
            Panel {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Field("URL del servidor", s.serverUrl, KeyboardType.Uri) { v -> store.update { it.copy(serverUrl = v) } }
                    Hint("Ej.: http://192.168.1.20:8000 (el notebook con server.py). Vacío = no enviar datos.")
                    if (link.enabled) {
                        Label(
                            if (link.connected) "✓ Conectado · ${link.samplesSent} muestras enviadas"
                            else "! Sin conexión" + (link.lastError?.let { " ($it)" } ?: ""),
                        )
                        Label(if (live.connected) "✓ Gestos aprendidos: en vivo" else "! Gestos aprendidos: sin conexión en vivo")
                    }
                }
            }

            SectionTitle("General")
            Panel {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Toggle("Hablar las opciones en voz alta", s.voiceEnabled) { v -> store.update { it.copy(voiceEnabled = v) } }
                    Toggle("Usar la linterna del celular como luz", s.phoneTorch) { v -> store.update { it.copy(phoneTorch = v) } }
                    Toggle("Iniciar al encender el teléfono", s.startOnBoot) { v -> store.update { it.copy(startOnBoot = v) } }
                }
            }
        }
    }
}

@Composable
private fun ActivationSettings(s: AppSettings, store: SettingsStore, serverConnected: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        for (mode in ActivationMode.entries) {
            val selected = s.activationMode == mode
            val shape = RoundedCornerShape(14.dp)
            Column(
                Modifier
                    .fillMaxWidth()
                    .background(if (selected) Palette.Highlight else Palette.Background, shape)
                    .border(1.dp, Palette.Border, shape)
                    .clickable { store.update { it.copy(activationMode = mode) } }
                    .padding(14.dp),
            ) {
                Text(
                    (if (selected) "● " else "○ ") + mode.label,
                    style = MaterialTheme.typography.titleMedium,
                    color = if (selected) Palette.OnHighlight else Palette.Text,
                )
                Text(
                    mode.description,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (selected) Palette.OnHighlight else Palette.Muted,
                )
            }
        }
        if (s.activationMode == ActivationMode.GESTURES) {
            Hint("✓ Los gestos corren en el celular, sin servidor. Enséñalos y enlázalos en la pestaña Gestos.")
        }
    }
}

@Composable
private fun DetectionSettings(s: AppSettings, store: SettingsStore) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Label("Velocidad del escaneo: una opción cada %.1f s".format(Locale.US, s.scanStepMs / 1000.0))
        AppSlider(s.scanStepMs.toFloat(), 1_000f..5_000f, steps = 15) { v ->
            store.update { it.copy(scanStepMs = (v / 250).toLong() * 250) }
        }
        val sensitivityWord = when {
            s.sensitivity < 0.8 -> "baja"
            s.sensitivity > 1.25 -> "alta"
            else -> "normal"
        }
        Label("Sensibilidad: $sensitivityWord (×%.2f)".format(Locale.US, s.sensitivity))
        AppSlider(s.sensitivity.toFloat(), 0.5f..2.0f, steps = 5) { v ->
            store.update { it.copy(sensitivity = (v * 4).toInt() / 4.0) }
        }
        Hint("Más sensibilidad = basta un movimiento más pequeño, pero hay más riesgo de activaciones sin querer.")
        Label("Tiempo que hay que sostener el imán: ${s.holdMs} ms")
        AppSlider(s.holdMs.toFloat(), 100f..1_000f, steps = 17) { v ->
            store.update { it.copy(holdMs = (v / 50).toLong() * 50) }
        }
    }
}

@Composable
private fun CaregiverSettings(s: AppSettings, store: SettingsStore) {
    val context = LocalContext.current
    var canCall by remember {
        mutableStateOf(context.checkSelfPermission(Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED)
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { canCall = it }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Field("Teléfono del cuidador", s.caregiverPhone, KeyboardType.Phone) { v -> store.update { it.copy(caregiverPhone = v) } }
        Field("Webhook (opcional)", s.caregiverWebhook, KeyboardType.Uri) { v -> store.update { it.copy(caregiverWebhook = v) } }
        Hint("Al confirmar \"Llamar cuidador\" se envía un POST al webhook y se llama al teléfono.")
        if (canCall) {
            Label("✓ Llamadas directas permitidas")
        } else {
            Hint("Sin permiso se abre el marcador y hay que tocar \"llamar\".")
            BigOutlineButton("Permitir llamadas directas", { permission.launch(Manifest.permission.CALL_PHONE) }, Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun DeviceEditor(
    device: Device,
    canDelete: Boolean,
    onChange: (Device) -> Unit,
    onDelete: () -> Unit,
    onTest: (on: Boolean) -> Unit,
) {
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                val currentKey = DeviceIconCatalog.normalize(device.icon)
                for (icon in Device.ICONS) {
                    val selected = DeviceIconCatalog.normalize(icon) == currentKey
                    Box(
                        Modifier
                            .size(52.dp)
                            .background(if (selected) Palette.Highlight else Palette.Background, RoundedCornerShape(10.dp))
                            .border(1.dp, Palette.Border, RoundedCornerShape(10.dp))
                            .clickable { onChange(device.copy(icon = icon)) },
                        contentAlignment = Alignment.Center,
                    ) {
                        DeviceVectorIcon(
                            icon = icon,
                            tint = if (selected) Palette.OnHighlight else Palette.Text,
                            size = 26.dp,
                        )
                    }
                }
            }
            Field("Nombre", device.name) { onChange(device.copy(name = it)) }
            if (device.kind == DeviceKind.SWITCH) {
                Field("URL para encender", device.onUrl, KeyboardType.Uri) { onChange(device.copy(onUrl = it)) }
                Field("URL para apagar", device.offUrl, KeyboardType.Uri) { onChange(device.copy(offUrl = it)) }
                Hint("Shelly: http://IP/relay/0?turn=on y ?turn=off. Vacío = modo demostración.")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    BigButton("Encender", { onTest(true) }, Modifier.weight(1f))
                    BigOutlineButton("Apagar", { onTest(false) }, Modifier.weight(1f))
                }
            } else {
                Hint("Usa el teléfono y webhook de la sección Cuidador. Siempre pide confirmación.")
                BigOutlineButton("Probar aviso", { onTest(true) }, Modifier.fillMaxWidth())
            }
            if (canDelete) {
                BigOutlineButton("Eliminar", onDelete, Modifier.fillMaxWidth())
            }
        }
    }
}

@Composable
private fun Label(text: String) = Text(text, style = MaterialTheme.typography.titleMedium, color = Palette.Text)

@Composable
private fun Hint(text: String) = Text(text, style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)

private const val MAX_DEVICES = 8
