package cl.magnesense.ui.gestures

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.MagneSenseApp
import cl.magnesense.data.ActivationMode
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.ConditionChip
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.ScreenColumn
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.delay
import java.util.Locale

/**
 * Gestos aprendidos (en el celular): estado del detector, asistente, ensenar gestos nuevos y la
 * lista de gestos con su accion. Los gestos se pueden probar aqui aunque el modo sea escaneo.
 */
@Composable
fun GesturesScreen(app: MagneSenseApp, onOpenSettings: () -> Unit, onOpenSetup: () -> Unit) {
    var teaching by rememberSaveable { mutableStateOf(false) }
    var draft by remember { mutableStateOf(TeachDraft()) }
    DisposableEffect(teaching) {
        app.gestures.teaching = teaching
        onDispose { app.gestures.teaching = false }
    }
    if (teaching) {
        TeachGestureFlow(app, draft, onClose = { teaching = false })
    } else {
        GestureList(
            app = app,
            onOpenSettings = onOpenSettings,
            onOpenSetup = onOpenSetup,
            onTeach = { d ->
                draft = d
                teaching = true
            },
        )
    }
}

@Composable
private fun GestureList(app: MagneSenseApp, onOpenSettings: () -> Unit, onOpenSetup: () -> Unit, onTeach: (TeachDraft) -> Unit) {
    val server by app.localGestures.state.collectAsState()
    val settings by app.settings.settings.collectAsState()
    val devices by app.access.devices.collectAsState()
    var flashing by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        app.gestures.fired.collect { f ->
            flashing = f.detector
            delay(FLASH_MS)
            if (flashing == f.detector) flashing = null
        }
    }

    Column(Modifier.verticalScroll(rememberScrollState())) {
        ScreenColumn {
            Text("Gestos aprendidos", style = MaterialTheme.typography.headlineMedium, color = Palette.Text)

            Panel {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        val p = server.phase2
                        ConditionChip(if (p.calibrating) "Calibrando…" else "Calibrado", !p.calibrating)
                        ConditionChip(
                            when {
                                !p.gyro -> "Sin giroscopio"
                                p.phoneMoving -> "Celular moviéndose"
                                else -> "Celular quieto"
                            },
                            p.gyro && !p.phoneMoving,
                        )
                    }
                    Text(
                        if (server.phase2.calibrating) "Deja el celular quieto y el imán lejos 2 segundos."
                        else "Ruido en reposo %.2f µT. Todo corre en el celular, sin servidor.".format(Locale.US, server.phase2.noise),
                        style = MaterialTheme.typography.bodyMedium,
                        color = Palette.Muted,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        BigOutlineButton("Recalibrar", app.localGestures::recalibrate, Modifier.weight(1f))
                        BigOutlineButton("Asistente de inicio", onOpenSetup, Modifier.weight(1f))
                    }
                    if (settings.activationMode != ActivationMode.GESTURES) {
                        Text(
                            "Ahora los gestos solo se pueden probar aquí. Para que actúen, activa el modo de gestos.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Palette.Muted,
                        )
                        BigOutlineButton("Usar gestos aprendidos", {
                            app.settings.update { it.copy(activationMode = ActivationMode.GESTURES) }
                        }, Modifier.fillMaxWidth())
                    }
                }
            }

            AssistantCard(app, onTeach = onTeach)

            BigButton("Enseñar un gesto", { onTeach(TeachDraft()) }, Modifier.fillMaxWidth())

            val detectors = server.phase2.detectors
            val forgotten = settings.gestureBindings.keys.filter { n -> detectors.none { it.name == n } }
            if (detectors.isEmpty() && forgotten.isEmpty()) {
                Text("Todavía no hay gestos aprendidos.", style = MaterialTheme.typography.bodyLarge, color = Palette.Muted)
            }
            for (d in detectors) {
                GestureCard(
                    name = d.name,
                    detector = d,
                    target = settings.gestureBindings[d.name],
                    devices = devices,
                    flashing = flashing == d.name,
                    onTarget = { t -> app.settings.update { it.copy(gestureBindings = it.gestureBindings + (d.name to t)) } },
                    onDelete = {
                        app.localGestures.removeDetector(d.name)
                        app.settings.update { it.copy(gestureBindings = it.gestureBindings - d.name) }
                    },
                )
            }
            for (name in forgotten) {
                GestureCard(
                    name = name,
                    detector = null,
                    target = settings.gestureBindings[name],
                    devices = devices,
                    flashing = false,
                    onTarget = { t -> app.settings.update { it.copy(gestureBindings = it.gestureBindings + (name to t)) } },
                    onDelete = { app.settings.update { it.copy(gestureBindings = it.gestureBindings - name) } },
                )
            }
        }
    }
}

private const val FLASH_MS = 1_000L
