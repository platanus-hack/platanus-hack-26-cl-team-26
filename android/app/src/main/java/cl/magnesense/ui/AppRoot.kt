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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.engine.Engine
import cl.magnesense.ui.calibration.CalibrationScreen
import cl.magnesense.ui.debug.DebugScreen
import cl.magnesense.ui.theme.Palette

enum class Screen(val label: String) {
    CALIBRATION("Calibrar"),
    DEBUG("Debug"),
}

/** Estructura general: pestanas grandes arriba (las usa el cuidador) y la pantalla activa. */
@Composable
fun AppRoot(engine: Engine) {
    var screen by rememberSaveable { mutableStateOf(Screen.CALIBRATION) }
    Column(Modifier.fillMaxSize()) {
        Tabs(screen) { screen = it }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (screen) {
                Screen.CALIBRATION -> CalibrationScreen(engine.detector, onDone = { screen = Screen.DEBUG })
                Screen.DEBUG -> DebugScreen(engine.detector)
            }
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
