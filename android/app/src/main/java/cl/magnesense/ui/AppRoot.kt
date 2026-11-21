package cl.magnesense.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.MagneSenseApp
import cl.magnesense.detector.DetectorState
import cl.magnesense.scanning.ScanMode
import cl.magnesense.ui.calibration.CalibrationScreen
import cl.magnesense.ui.control.ConfirmOverlay
import cl.magnesense.ui.control.ControlScreen
import cl.magnesense.ui.control.PauseOverlay
import cl.magnesense.ui.debug.DebugScreen
import cl.magnesense.ui.gestures.GesturesScreen
import cl.magnesense.ui.history.HistoryScreen
import cl.magnesense.ui.pulses.PulsesScreen
import cl.magnesense.ui.settings.SettingsScreen
import cl.magnesense.data.ActivationMode
import cl.magnesense.ui.setup.SetupWizard
import cl.magnesense.ui.theme.Palette
import cl.magnesense.ui.tracker.TrackerScreen

enum class Screen(val label: String) {
    PULSES("Pulsos"),
    CONTROL("Control"),
    GESTURES("Gestos"),
    TRACKER("3D"),
    CALIBRATION("Calibrar"),
    HISTORY("Historial"),
    SETTINGS("Ajustes"),
    DEBUG("Debug"),
}

/** Estructura general: pestanas grandes arriba (las usa el cuidador) y la pantalla activa. */
@Composable
fun AppRoot(app: MagneSenseApp) {
    val engine = app.engine
    val access = app.access
    var screen by rememberSaveable {
        mutableStateOf(if (app.settings.settings.value.activationMode == ActivationMode.PULSES) Screen.PULSES else Screen.CONTROL)
    }
    val detector by engine.detector.status.collectAsState()
    val scan by access.scanning.state.collectAsState()
    // La primera vez se abre el asistente de inicio (imán, calibrar, gestos).
    var teachRequest by rememberSaveable { mutableStateOf(false) }
    var setup by rememberSaveable {
        mutableStateOf(!app.settings.settings.value.setupDone && app.settings.settings.value.activationMode == ActivationMode.GESTURES)
    }

    // En estas pantallas el iman se mueve a proposito: Pulsos no debe actuar (ver PulseRules).
    val calibrating = setup || screen in MAGNET_BUSY_SCREENS
    SideEffect { app.screenBusy = calibrating }
    val pulsesMode = app.settings.settings.collectAsState().value.activationMode == ActivationMode.PULSES

    if (setup) {
        SetupWizard(app, onDone = {
            app.settings.update { it.copy(setupDone = true) }
            setup = false
            screen = Screen.GESTURES
        })
        return
    }

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            Tabs(screen) { screen = it }
            if (calibrating && pulsesMode) {
                Text(
                    "Pulsos en pausa mientras calibras",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Palette.Muted,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (screen) {
                    Screen.PULSES -> PulsesScreen(app)
                    Screen.CONTROL -> ControlScreen(app, onCalibrate = { screen = Screen.CALIBRATION }, onTeachGesture = {
                        teachRequest = true
                        screen = Screen.GESTURES
                    })
                    Screen.GESTURES -> GesturesScreen(
                        app,
                        onOpenSettings = { screen = Screen.SETTINGS },
                        onOpenSetup = { setup = true },
                        startTeaching = teachRequest,
                        onTeachStarted = { teachRequest = false },
                    )
                    Screen.TRACKER -> TrackerScreen(app)
                    Screen.CALIBRATION -> CalibrationScreen(engine.detector, onDone = { screen = Screen.CONTROL })
                    Screen.HISTORY -> HistoryScreen(app.history, app.diag)
                    Screen.SETTINGS -> SettingsScreen(app.settings, access.actions, app.telemetry, app.server)
                    Screen.DEBUG -> DebugScreen(engine.detector, app.settings, app.server)
                }
            }
        }
        if (screen == Screen.CONTROL && detector.state == DetectorState.PAUSED) {
            PauseOverlay(detector.progress)
        }
        if (scan.mode == ScanMode.CONFIRMING) {
            ConfirmOverlay(scan, onChoice = access.scanning::confirmByTouch)
        }
    }
}

@Composable
private fun Tabs(current: Screen, onSelect: (Screen) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 8.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        for (s in Screen.entries) {
            val selected = s == current
            TextButton(
                onClick = { onSelect(s) },
                modifier = Modifier
                    .heightIn(min = 52.dp)
                    .background(if (selected) Palette.Highlight else Palette.Surface, RoundedCornerShape(12.dp)),
            ) {
                Text(
                    s.label,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (selected) Palette.OnHighlight else Palette.Text,
                )
            }
        }
    }
}

/** Pantallas donde el iman se acerca y aleja a proposito (calibrar, probar). */
private val MAGNET_BUSY_SCREENS = setOf(Screen.CALIBRATION, Screen.TRACKER, Screen.DEBUG)
