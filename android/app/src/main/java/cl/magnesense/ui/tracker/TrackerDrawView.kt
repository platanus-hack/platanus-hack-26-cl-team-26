package cl.magnesense.ui.tracker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.unit.dp
import cl.magnesense.tracking.TrackState
import cl.magnesense.tracking.TrackerUiState
import cl.magnesense.ui.components.AppSlider
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.theme.Palette
import java.util.Locale

/**
 * Dibujar con el dedo: la posicion x/y del iman mueve el lapiz sobre la hoja.
 * Con el dedo bajo (z menor que el limite) dibuja; al levantarlo se mueve sin dibujar.
 */
@Composable
fun TrackerDrawView(ui: TrackerUiState, modifier: Modifier = Modifier) {
    val strokes = remember { mutableStateListOf<List<Offset>>() }
    val current = remember { mutableStateListOf<Offset>() }
    var cursor by remember { mutableStateOf<Offset?>(null) }
    var penDown by remember { mutableStateOf(false) }
    var penLimitCm by remember { mutableFloatStateOf(((ui.refCm ?: 3.0) + 1.0).toFloat()) }

    fun endStroke() {
        if (current.isNotEmpty()) {
            strokes += current.toList()
            current.clear()
        }
    }

    // Cada nueva posicion (ya filtrada): agregarla al trazo si el lapiz esta abajo.
    // Una lectura descartada corta el trazo en vez de unir con una linea recta.
    LaunchedEffect(ui) {
        val p = ui.display
        if (ui.result.state != TrackState.TRACKING || p == null || ui.phoneMoving) {
            endStroke()
            penDown = false
            return@LaunchedEffect
        }
        if (!ui.reliable) {
            endStroke()
            return@LaunchedEffect
        }
        // Siempre dentro de la hoja: fuera de ella el lapiz queda en el borde.
        val pos = Offset(
            p.x.toFloat().coerceIn(-HALF_RANGE_CM, HALF_RANGE_CM),
            p.y.toFloat().coerceIn(-HALF_RANGE_CM, HALF_RANGE_CM),
        )
        cursor = pos
        penDown = p.z < penLimitCm
        if (penDown) current += pos else endStroke()
    }

    Column(modifier, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            if (penDown) "● Dibujando: levanta el dedo para mover sin dibujar"
            else "○ Lápiz arriba: baja el dedo (más cerca que %.1f cm) para dibujar".format(Locale.US, penLimitCm),
            style = MaterialTheme.typography.titleMedium,
            color = if (penDown) Palette.Highlight else Palette.Text,
        )
        Canvas(
            Modifier
                .fillMaxWidth()
                .weight(1f)
                .background(Palette.Surface, RoundedCornerShape(20.dp))
                .border(1.dp, Palette.Border, RoundedCornerShape(20.dp)),
        ) {
            val sheet = sheetRect()
            drawRect(Palette.Background, topLeft = sheet.topLeft, size = sheet.size)
            clipRect(sheet.left, sheet.top, sheet.right, sheet.bottom) {
                drawPaperGrid()
                val width = 12.dp.toPx()
                for (s in strokes) drawStroke(s, width)
                drawStroke(current, width)
                cursor?.let { c ->
                    val at = toCanvas(c)
                    if (penDown) {
                        drawCircle(Palette.Highlight, radius = 14.dp.toPx(), center = at)
                    } else {
                        drawCircle(Palette.Text, radius = 14.dp.toPx(), center = at, style = Stroke(width = 3.dp.toPx()))
                    }
                }
            }
            drawRect(Palette.Border, topLeft = sheet.topLeft, size = sheet.size, style = Stroke(width = 2.dp.toPx()))
        }
        Text("Altura para dibujar: %.1f cm".format(Locale.US, penLimitCm), style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
        AppSlider(penLimitCm, 1.5f..10f, steps = 16) { penLimitCm = it }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            BigOutlineButton("Deshacer", { if (strokes.isNotEmpty()) strokes.removeAt(strokes.lastIndex) }, Modifier.weight(1f))
            BigOutlineButton("Borrar", {
                strokes.clear()
                current.clear()
            }, Modifier.weight(1f))
        }
    }
}

/** La hoja: un cuadrado centrado que representa ±[HALF_RANGE_CM] cm alrededor del sensor. */
private fun DrawScope.sheetRect(): Rect {
    val side = minOf(size.width, size.height)
    val left = (size.width - side) / 2
    val top = (size.height - side) / 2
    return Rect(left, top, left + side, top + side)
}

private fun DrawScope.toCanvas(cm: Offset): Offset {
    val sheet = sheetRect()
    return Offset(
        sheet.left + (cm.x + HALF_RANGE_CM) / (2 * HALF_RANGE_CM) * sheet.width,
        sheet.top + (HALF_RANGE_CM - cm.y) / (2 * HALF_RANGE_CM) * sheet.height,
    )
}

private fun DrawScope.drawPaperGrid() {
    for (i in -6..6 step 2) {
        val v = i.toFloat()
        drawLine(Palette.Border, toCanvas(Offset(v, -HALF_RANGE_CM)), toCanvas(Offset(v, HALF_RANGE_CM)), strokeWidth = 1.5f)
        drawLine(Palette.Border, toCanvas(Offset(-HALF_RANGE_CM, v)), toCanvas(Offset(HALF_RANGE_CM, v)), strokeWidth = 1.5f)
    }
}

private fun DrawScope.drawStroke(points: List<Offset>, width: Float) {
    if (points.isEmpty()) return
    if (points.size == 1) {
        drawCircle(Palette.Highlight, radius = width / 2, center = toCanvas(points[0]))
        return
    }
    val path = Path()
    points.forEachIndexed { i, p ->
        val c = toCanvas(p)
        if (i == 0) path.moveTo(c.x, c.y) else path.lineTo(c.x, c.y)
    }
    drawPath(path, Palette.Highlight, style = Stroke(width = width, cap = StrokeCap.Round, join = StrokeJoin.Round))
}

private const val HALF_RANGE_CM = 6f
