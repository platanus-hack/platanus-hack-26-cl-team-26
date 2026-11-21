package cl.magnesense.ui.control

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import cl.magnesense.scanning.ScanState
import cl.magnesense.ui.theme.Palette

/** Fondo que tapa la pantalla y bloquea los toques de abajo. */
@Composable
private fun Scrim(content: @Composable () -> Unit) {
    Box(
        Modifier
            .fillMaxSize()
            .background(Palette.Background.copy(alpha = 0.97f))
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) { content() }
}

/** Confirmacion de una accion critica: "Si / No" se recorren por voz; tambien se pueden tocar. */
@Composable
fun ConfirmOverlay(scan: ScanState, onChoice: (yes: Boolean) -> Unit) {
    Scrim {
        Column(verticalArrangement = Arrangement.spacedBy(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                scan.pending?.confirmPrompt ?: "¿Confirmar?",
                style = MaterialTheme.typography.displayMedium,
                color = Palette.Text,
                textAlign = TextAlign.Center,
            )
            scan.confirmChoices.forEachIndexed { i, label ->
                ChoiceButton(label, highlighted = i == scan.confirmIndex) { onChoice(i == 0) }
            }
            Text(
                "Se cancela solo en ${scan.confirmSecondsLeft} s",
                style = MaterialTheme.typography.titleMedium,
                color = Palette.Muted,
            )
        }
    }
}

@Composable
private fun ChoiceButton(label: String, highlighted: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(20.dp)
    Box(
        Modifier
            .fillMaxWidth()
            .height(120.dp)
            .background(if (highlighted) Palette.Highlight else Palette.Surface, shape)
            .border(if (highlighted) 5.dp else 1.dp, if (highlighted) Palette.Text else Palette.Border, shape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            (if (highlighted) "▶ " else "") + label,
            style = MaterialTheme.typography.headlineMedium,
            color = if (highlighted) Palette.OnHighlight else Palette.Text,
        )
    }
}

/** El giroscopio detecto movimiento: no se activa nada hasta que el celular quede quieto. */
@Composable
fun PauseOverlay(progress: Double) {
    Scrim {
        Column(verticalArrangement = Arrangement.spacedBy(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("En pausa", style = MaterialTheme.typography.displayMedium, color = Palette.Warning)
            Text(
                "El celular se movió. No vamos a activar nada hasta que quede quieto.",
                style = MaterialTheme.typography.headlineMedium,
                color = Palette.Text,
                textAlign = TextAlign.Center,
            )
            LinearProgressIndicator(
                progress = { progress.toFloat() },
                modifier = Modifier.fillMaxWidth().height(18.dp),
                color = Palette.WarningSoft,
                trackColor = Palette.Border,
                drawStopIndicator = {},
            )
        }
    }
}
