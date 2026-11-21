package cl.magnesense.ui.gestures

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.actions.Device
import cl.magnesense.data.AppSettings
import cl.magnesense.gestures.GestureMatcher
import cl.magnesense.remote.DetectorType
import cl.magnesense.remote.RemoteDetector
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.DeviceVectorIcon
import cl.magnesense.ui.theme.Palette

/** Una opcion: valor guardado, texto y (opcional) icono vectorial del dispositivo. */
data class Choice(val value: String, val label: String, val icon: String? = null)

/** Fila de opciones grandes; la elegida va en ambar. */
@Composable
fun ChoiceRow(options: List<Choice>, selected: String?, onSelect: (String) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for ((value, label, icon) in options) {
            val on = value == selected
            val shape = RoundedCornerShape(12.dp)
            Row(
                Modifier
                    .heightIn(min = 52.dp)
                    .background(if (on) Palette.Highlight else Palette.Background, shape)
                    .border(1.dp, if (on) Palette.Highlight else Palette.Border, shape)
                    .clickable { onSelect(value) }
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                icon?.let { DeviceVectorIcon(it, tint = if (on) Palette.OnHighlight else Palette.Text, size = 24.dp) }
                Text(label, style = MaterialTheme.typography.titleMedium, color = if (on) Palette.OnHighlight else Palette.Text)
            }
        }
    }
}

/** Que hace un gesto: un sonido, un dispositivo, abrir el escaneo o nada. */
@Composable
fun TargetPicker(devices: List<Device>, selected: String?, onSelect: (String) -> Unit) {
    val options = listOf(Choice(AppSettings.BIND_SONG, "♪ Canción"), Choice(AppSettings.BIND_QUACK, "🦆 Cuack")) +
        devices.map { Choice(it.id, it.name, it.icon) } +
        listOf(Choice(AppSettings.BIND_SCAN, "Abrir escaneo"), Choice(AppSettings.BIND_NONE, "Nada (solo probar)"))
    ChoiceRow(options, selected, onSelect)
}

fun targetLabel(target: String?, devices: List<Device>): String = when (target) {
    null, AppSettings.BIND_NONE -> "Sin acción"
    AppSettings.BIND_SCAN -> "Abre el escaneo"
    AppSettings.BIND_SONG -> "Pone o para la canción"
    AppSettings.BIND_QUACK -> "Cuack de pato"
    else -> devices.firstOrNull { it.id == target }?.name ?: "Sin acción"
}

fun ruleLabel(d: RemoteDetector): String = when (d.type) {
    DetectorType.EVENT -> "Movimiento breve · se activa: ${GestureMatcher.triggerLabel(d.trigger)}"
    DetectorType.STATE -> "Posición · se activa al pasar a \"${d.trigger}\""
    DetectorType.RHYTHM -> "Movimiento repetido · se activa cuando se detiene"
}

/**
 * Un gesto aprendido. Se pone ambar un segundo cada vez que se dispara, para probarlo en vivo.
 * [detector] es null si ya no esta aprendido (solo queda su accion guardada).
 */
@Composable
fun GestureCard(
    name: String,
    detector: RemoteDetector?,
    target: String?,
    devices: List<Device>,
    flashing: Boolean,
    onTarget: (String) -> Unit,
    onDelete: () -> Unit,
) {
    var editing by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(16.dp)
    val textColor = if (flashing) Palette.OnHighlight else Palette.Text
    val mutedColor = if (flashing) Palette.OnHighlight else Palette.Muted
    Column(
        Modifier
            .fillMaxWidth()
            .background(if (flashing) Palette.Highlight else Palette.Surface, shape)
            .border(if (flashing) 4.dp else 1.dp, if (flashing) Palette.Text else Palette.Border, shape)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(name, style = MaterialTheme.typography.titleLarge, color = textColor)
        if (detector == null) {
            Text(
                "! Este gesto ya no está aprendido: vuelve a enseñarlo.",
                style = MaterialTheme.typography.bodyMedium,
                color = if (flashing) Palette.OnHighlight else Palette.WarningSoft,
            )
        } else {
            Text(ruleLabel(detector), style = MaterialTheme.typography.bodyMedium, color = mutedColor)
            Text("Detectado ${detector.count} veces", style = MaterialTheme.typography.bodyMedium, color = mutedColor)
        }
        Text("Acción: ${targetLabel(target, devices)}", style = MaterialTheme.typography.titleMedium, color = textColor)
        if (editing) {
            TargetPicker(devices, target) {
                onTarget(it)
                editing = false
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BigOutlineButton(if (editing) "Listo" else "Cambiar acción", { editing = !editing }, Modifier.weight(1f))
            if (confirmDelete) {
                BigButton("¿Seguro? Eliminar", onDelete, Modifier.weight(1f))
            } else {
                BigOutlineButton("Eliminar", { confirmDelete = true }, Modifier.weight(1f))
            }
        }
    }
}
