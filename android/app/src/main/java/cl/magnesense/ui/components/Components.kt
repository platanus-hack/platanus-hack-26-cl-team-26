package cl.magnesense.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import kotlin.math.max
import cl.magnesense.ui.theme.Palette

/** Tarjeta con borde, base de casi todas las pantallas. */
@Composable
fun Panel(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Box(
        modifier
            .fillMaxWidth()
            .background(Palette.Surface, RoundedCornerShape(16.dp))
            .border(1.dp, Palette.Border, RoundedCornerShape(16.dp))
            .padding(16.dp),
    ) { content() }
}

/** Pildora de estado. Siempre lleva texto, el color es solo apoyo. */
@Composable
fun StatusPill(text: String, color: Color, modifier: Modifier = Modifier) {
    Box(
        modifier
            .background(color, RoundedCornerShape(50))
            .padding(horizontal = 20.dp, vertical = 10.dp),
    ) {
        Text(text, color = Palette.OnHighlight, style = MaterialTheme.typography.titleMedium)
    }
}

/** Chip de condicion del sensor: simbolo + texto, para no depender del color. */
@Composable
fun ConditionChip(label: String, ok: Boolean, modifier: Modifier = Modifier) {
    val color = if (ok) Palette.Ok else Palette.Warning
    Row(
        modifier
            .border(2.dp, color, RoundedCornerShape(50))
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(if (ok) "✓ " else "! ", color = color, style = MaterialTheme.typography.labelLarge)
        Text(label, color = Palette.Text, style = MaterialTheme.typography.bodyMedium)
    }
}

/** Fila "nombre: valor" en tipografia monoespaciada para la pantalla de depuracion. */
@Composable
fun ValueRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = Palette.Muted, style = MaterialTheme.typography.bodyMedium)
        Text(value, color = Palette.Text, style = MaterialTheme.typography.bodyMedium, fontFamily = FontFamily.Monospace)
    }
}

@Composable
fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleLarge, color = Palette.Text, modifier = Modifier.padding(bottom = 8.dp))
}

/** Boton primario grande (ambar). */
@Composable
fun BigButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = 64.dp),
        shape = RoundedCornerShape(14.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Palette.Highlight, contentColor = Palette.OnHighlight),
    ) { Text(text, style = MaterialTheme.typography.titleMedium) }
}

/** Boton secundario grande (borde). */
@Composable
fun BigOutlineButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = 64.dp),
        shape = RoundedCornerShape(14.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = Palette.Text),
    ) { Text(text, style = MaterialTheme.typography.titleMedium) }
}

@Composable
fun ScreenColumn(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { content() }
}

/** Barra de la senal actual con lectura en µT y umbral visible para el jurado y el cuidador. */
@Composable
fun SignalMeter(signal: Double, marker: Double, modifier: Modifier = Modifier) {
    val scale = max(marker * 2, signal).coerceAtLeast(1.0) * 1.1
    val above = marker > 0 && signal >= marker
    val barColor = if (above) Palette.Highlight else Palette.Ok
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                "Señal: %.1f µT".format(java.util.Locale.US, signal),
                color = if (above) Palette.Highlight else Palette.Text,
                style = MaterialTheme.typography.bodyMedium,
                fontFamily = FontFamily.Monospace,
            )
            Text(
                "Umbral: %.1f µT".format(java.util.Locale.US, marker),
                color = Palette.Muted,
                style = MaterialTheme.typography.bodyMedium,
                fontFamily = FontFamily.Monospace,
            )
        }
        Box(
            Modifier
                .fillMaxWidth()
                .height(24.dp)
                .background(Palette.Background, RoundedCornerShape(6.dp))
                .border(1.dp, if (above) Palette.Highlight else Palette.Border, RoundedCornerShape(6.dp)),
        ) {
            Box(
                Modifier
                    .fillMaxWidth((signal / scale).toFloat().coerceIn(0f, 1f))
                    .height(24.dp)
                    .background(barColor, RoundedCornerShape(6.dp)),
            )
            Box(
                Modifier
                    .fillMaxWidth((marker / scale).toFloat().coerceIn(0f, 1f))
                    .height(24.dp),
                contentAlignment = Alignment.CenterEnd,
            ) { Box(Modifier.size(width = 4.dp, height = 24.dp).background(Palette.Highlight)) }
        }
    }
}

@Composable
fun AppSlider(value: Float, range: ClosedFloatingPointRange<Float>, steps: Int, onChange: (Float) -> Unit) {
    Slider(
        value = value.coerceIn(range),
        onValueChange = onChange,
        valueRange = range,
        steps = steps,
        colors = SliderDefaults.colors(
            thumbColor = Palette.Highlight,
            activeTrackColor = Palette.Highlight,
            inactiveTrackColor = Palette.Border,
        ),
    )
}

@Composable
fun Toggle(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyLarge, color = Palette.Text, modifier = Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(checkedTrackColor = Palette.Highlight, checkedThumbColor = Palette.OnHighlight),
        )
    }
}
