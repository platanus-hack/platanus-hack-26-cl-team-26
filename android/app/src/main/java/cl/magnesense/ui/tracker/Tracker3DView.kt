package cl.magnesense.ui.tracker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import cl.magnesense.tracking.TrackPoint
import cl.magnesense.tracking.TrackState
import cl.magnesense.tracking.TrackerUiState
import cl.magnesense.ui.theme.Palette
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/**
 * Vista 3D del iman respecto al celular (como el panel del servidor): grilla en la mesa,
 * contorno del telefono, ejes, sensor, estela y el iman con su sombra.
 * Arrastrar gira la camara; pellizcar acerca.
 */
@Composable
fun Tracker3DView(ui: TrackerUiState, modifier: Modifier = Modifier) {
    var yaw by remember { mutableFloatStateOf(-0.6f) }
    var pitch by remember { mutableFloatStateOf(0.9f) }
    var zoom by remember { mutableFloatStateOf(1.7f) }

    Canvas(
        modifier
            .background(Palette.Background)
            .pointerInput(Unit) {
                detectTransformGestures { _, pan, zoomChange, _ ->
                    yaw += pan.x * 0.01f
                    pitch = (pitch - pan.y * 0.01f).coerceIn(0.05f, 1.55f)
                    zoom = (zoom * zoomChange).coerceIn(0.4f, 4f)
                }
            },
    ) {
        val cam = Camera(yaw.toDouble(), pitch.toDouble(), zoom.toDouble(), size)
        drawGrid(cam)
        drawPhone(cam)
        drawAxes(cam)
        drawCircle(Palette.Text, radius = 6f, center = cam.project(0.0, 0.0, 0.0).offset)
        drawTrail(cam, ui.trail)
        val point = ui.display
        if (ui.result.state == TrackState.TRACKING && point != null) {
            drawMagnet(cam, point, ui.result.confidence, ui.reliable)
        }
    }
}

/** Color del iman segun cuanto calza el modelo; siempre acompanado de texto en la pantalla. */
fun confidenceColor(confidence: Double): Color = when {
    confidence >= 0.8 -> Palette.Highlight
    confidence >= 0.5 -> Palette.Text
    else -> Palette.Warning
}

private class Projected(val offset: Offset, val scale: Float)

/** Camara en orbita: yaw gira sobre z; pitch es la elevacion (0 = de lado, π/2 = desde arriba). */
private class Camera(yaw: Double, pitch: Double, zoom: Double, private val size: Size) {
    private val cy = cos(yaw)
    private val sy = sin(yaw)
    private val cp = cos(pitch)
    private val sp = sin(pitch)
    private val scale = min(size.width, size.height) / 26.0 * zoom

    /** Punto en cm (ejes del telefono) → pantalla, con una perspectiva suave (camara a 60 cm). */
    fun project(x: Double, y: Double, z: Double): Projected {
        val x1 = x * cy - y * sy
        val y1 = x * sy + y * cy
        val up = y1 * sp + z * cp
        val depth = -y1 * cp + z * sp
        val f = 60.0 / (60.0 - depth).coerceAtLeast(10.0)
        return Projected(
            Offset((size.width / 2 + x1 * scale * f).toFloat(), (size.height * 0.55 - up * scale * f).toFloat()),
            f.toFloat(),
        )
    }
}

private fun DrawScope.line3d(cam: Camera, a: TrackPoint, b: TrackPoint, color: Color, width: Float, dashed: Boolean = false) {
    drawLine(
        color,
        cam.project(a.x, a.y, a.z).offset,
        cam.project(b.x, b.y, b.z).offset,
        strokeWidth = width,
        pathEffect = if (dashed) PathEffect.dashPathEffect(floatArrayOf(14f, 10f)) else null,
    )
}

private fun DrawScope.drawGrid(cam: Camera) {
    val grid = Palette.Border
    for (i in -8..8 step 2) {
        line3d(cam, TrackPoint(i.toDouble(), -8.0, 0.0), TrackPoint(i.toDouble(), 8.0, 0.0), grid, 1.5f)
        line3d(cam, TrackPoint(-8.0, i.toDouble(), 0.0), TrackPoint(8.0, i.toDouble(), 0.0), grid, 1.5f)
    }
}

/** Contorno del celular: el sensor esta cerca del borde superior. */
private fun DrawScope.drawPhone(cam: Camera) {
    val c = listOf(TrackPoint(-3.5, -12.0, 0.0), TrackPoint(3.5, -12.0, 0.0), TrackPoint(3.5, 3.0, 0.0), TrackPoint(-3.5, 3.0, 0.0))
    for (i in c.indices) line3d(cam, c[i], c[(i + 1) % c.size], Palette.Muted, 3f, dashed = true)
}

private fun DrawScope.drawAxes(cam: Camera) {
    val o = TrackPoint(0.0, 0.0, 0.0)
    line3d(cam, o, TrackPoint(3.0, 0.0, 0.0), Palette.Warning, 4f)
    line3d(cam, o, TrackPoint(0.0, 3.0, 0.0), Palette.Ok, 4f)
    line3d(cam, o, TrackPoint(0.0, 0.0, 3.0), Palette.Text, 4f)
}

private fun DrawScope.drawTrail(cam: Camera, trail: List<TrackPoint>) {
    if (trail.size < 2) return
    for (i in 1 until trail.size) {
        val alpha = i.toFloat() / trail.size
        line3d(cam, trail[i - 1], trail[i], Palette.Highlight.copy(alpha = alpha), 5f)
    }
}

/** [reliable] = false: la ultima lectura se descarto y se muestra la posicion anterior, atenuada. */
private fun DrawScope.drawMagnet(cam: Camera, p: TrackPoint, confidence: Double, reliable: Boolean) {
    val floor = TrackPoint(p.x, p.y, 0.0)
    line3d(cam, p, floor, Palette.Muted, 2f, dashed = true)
    val shadow = cam.project(floor.x, floor.y, 0.0)
    drawOval(
        Color.Black.copy(alpha = 0.45f),
        topLeft = shadow.offset - Offset(16f * shadow.scale, 7f * shadow.scale),
        size = Size(32f * shadow.scale, 14f * shadow.scale),
    )
    val at = cam.project(p.x, p.y, p.z)
    val r = 16f * at.scale
    drawCircle(confidenceColor(confidence).copy(alpha = if (reliable) 1f else 0.4f), radius = r, center = at.offset)
    drawCircle(Palette.Background, radius = r, center = at.offset, style = Stroke(width = 3f))
}
