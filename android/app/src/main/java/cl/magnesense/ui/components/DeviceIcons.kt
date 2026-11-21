package cl.magnesense.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import cl.magnesense.ui.theme.Palette

/**
 * Iconografia vectorial propia (sin emojis) de alto contraste para dispositivos y estados.
 * Acepta tanto claves semanticas ("bulb", "fan", "tv", "phone"...) como los emojis antiguos
 * ("💡", "🌀", "📺", "📞"...) para mantener compatibilidad con ajustes ya guardados.
 */
object DeviceIconCatalog {
    val ALL = listOf(
        "bulb",
        "fan",
        "tv",
        "phone",
        "plug",
        "bed",
        "music",
        "door",
        "bell",
        "ac",
        "heater",
        "radio",
    )

    fun normalize(raw: String): String = when (raw.trim()) {
        "💡", "bulb", "light" -> "bulb"
        "🌀", "fan" -> "fan"
        "📺", "tv" -> "tv"
        "📞", "phone", "caregiver" -> "phone"
        "🔌", "plug" -> "plug"
        "🛏️", "🛏", "bed" -> "bed"
        "🎵", "music" -> "music"
        "🚪", "door" -> "door"
        "🔔", "bell" -> "bell"
        "❄️", "❄", "ac", "cold" -> "ac"
        "🔥", "heater", "fire" -> "heater"
        "📻", "radio" -> "radio"
        else -> "plug"
    }
}

/** Medallon circular con el icono vectorial del dispositivo, pensado para leerse a 2 m. */
@Composable
fun DeviceBadgeIcon(
    icon: String,
    on: Boolean,
    highlighted: Boolean,
    modifier: Modifier = Modifier,
    badgeSize: Dp = 56.dp,
    iconSize: Dp = 32.dp,
) {
    val bg = when {
        highlighted -> Palette.OnHighlight.copy(alpha = 0.14f)
        on -> Palette.Ok.copy(alpha = 0.18f)
        else -> Palette.Background.copy(alpha = 0.65f)
    }
    val border = when {
        highlighted -> Palette.OnHighlight.copy(alpha = 0.35f)
        on -> Palette.Ok
        else -> Palette.Border
    }
    val tint = when {
        highlighted -> Palette.OnHighlight
        on -> Palette.Ok
        else -> Palette.Text
    }
    Box(
        modifier
            .size(badgeSize)
            .background(bg, CircleShape)
            .border(if (on || highlighted) 2.dp else 1.dp, border, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        DeviceVectorIcon(icon = icon, tint = tint, size = iconSize)
    }
}

/** Dibuja un icono vectorial limpio sobre una grilla normalizada de 24x24. */
@Composable
fun DeviceVectorIcon(
    icon: String,
    tint: Color,
    modifier: Modifier = Modifier,
    size: Dp = 28.dp,
) {
    val key = DeviceIconCatalog.normalize(icon)
    Canvas(modifier.size(size)) {
        val s = this.size.minDimension / 24f
        val stroke = Stroke(
            width = 2.1f * s,
            cap = StrokeCap.Round,
            join = StrokeJoin.Round,
        )
        when (key) {
            "bulb" -> drawBulb(s, tint, stroke)
            "fan" -> drawFan(s, tint, stroke)
            "tv" -> drawTv(s, tint, stroke)
            "phone" -> drawPhone(s, tint, stroke)
            "plug" -> drawPlug(s, tint, stroke)
            "bed" -> drawBed(s, tint, stroke)
            "music" -> drawMusic(s, tint, stroke)
            "door" -> drawDoor(s, tint, stroke)
            "bell" -> drawBell(s, tint, stroke)
            "ac" -> drawSnowflake(s, tint, stroke)
            "heater" -> drawFlame(s, tint, stroke)
            "radio" -> drawRadio(s, tint, stroke)
            else -> drawPlug(s, tint, stroke)
        }
    }
}

private fun DrawScope.drawBulb(s: Float, color: Color, stroke: Stroke) {
    val p = Path().apply {
        addArc(Rect(6.2f * s, 3.2f * s, 17.8f * s, 14.8f * s), 140f, 260f)
        lineTo(14.5f * s, 16.5f * s)
        lineTo(9.5f * s, 16.5f * s)
        close()
    }
    drawPath(p, color, style = stroke)
    drawLine(color, Offset(9.5f * s, 19.2f * s), Offset(14.5f * s, 19.2f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(10.5f * s, 21.5f * s), Offset(13.5f * s, 21.5f * s), stroke.width, StrokeCap.Round)
    // Filamento interior
    drawLine(color, Offset(12f * s, 11f * s), Offset(12f * s, 16f * s), stroke.width * 0.75f, StrokeCap.Round)
}

private fun DrawScope.drawFan(s: Float, color: Color, stroke: Stroke) {
    val center = Offset(12f * s, 12f * s)
    for (angle in listOf(0f, 90f, 180f, 270f)) {
        rotate(angle, center) {
            val blade = Path().apply {
                moveTo(12f * s, 9.8f * s)
                cubicTo(12f * s, 4.2f * s, 16.8f * s, 3.5f * s, 17.5f * s, 7.2f * s)
                cubicTo(18.0f * s, 9.6f * s, 14.8f * s, 11.2f * s, 13.8f * s, 11.2f * s)
                close()
            }
            drawPath(blade, color, style = stroke)
        }
    }
    drawCircle(color, radius = 2.1f * s, center = center)
}

private fun DrawScope.drawTv(s: Float, color: Color, stroke: Stroke) {
    drawRoundRect(
        color = color,
        topLeft = Offset(3f * s, 5f * s),
        size = Size(18f * s, 11.8f * s),
        cornerRadius = CornerRadius(2.2f * s, 2.2f * s),
        style = stroke,
    )
    drawLine(color, Offset(12f * s, 16.8f * s), Offset(12f * s, 20.2f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(7.5f * s, 20.2f * s), Offset(16.5f * s, 20.2f * s), stroke.width, StrokeCap.Round)
    // Triangulo de play sutil adentro
    val play = Path().apply {
        moveTo(10.5f * s, 8.8f * s)
        lineTo(14.5f * s, 10.9f * s)
        lineTo(10.5f * s, 13.0f * s)
        close()
    }
    drawPath(play, color)
}

private fun DrawScope.drawPhone(s: Float, color: Color, stroke: Stroke) {
    val handset = Path().apply {
        moveTo(6.5f * s, 4.5f * s)
        lineTo(9.5f * s, 4.5f * s)
        lineTo(11.0f * s, 8.2f * s)
        lineTo(9.0f * s, 10.0f * s)
        cubicTo(10.2f * s, 12.5f * s, 11.5f * s, 13.8f * s, 14.0f * s, 15.0f * s)
        lineTo(15.8f * s, 13.0f * s)
        lineTo(19.5f * s, 14.5f * s)
        lineTo(19.5f * s, 17.5f * s)
        cubicTo(19.5f * s, 19.2f * s, 17.5f * s, 20.2f * s, 15.2f * s, 19.8f * s)
        cubicTo(9.5f * s, 18.8f * s, 5.2f * s, 14.5f * s, 4.2f * s, 8.8f * s)
        cubicTo(3.8f * s, 6.5f * s, 4.8f * s, 4.5f * s, 6.5f * s, 4.5f * s)
        close()
    }
    drawPath(handset, color, style = stroke)
    // Ondas de llamada activa arriba a la derecha
    drawArc(
        color = color,
        startAngle = -85f,
        sweepAngle = 80f,
        useCenter = false,
        topLeft = Offset(11.5f * s, 4.5f * s),
        size = Size(8f * s, 8f * s),
        style = stroke,
    )
}

private fun DrawScope.drawPlug(s: Float, color: Color, stroke: Stroke) {
    drawLine(color, Offset(9.5f * s, 4f * s), Offset(9.5f * s, 8.5f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(14.5f * s, 4f * s), Offset(14.5f * s, 8.5f * s), stroke.width, StrokeCap.Round)
    val body = Path().apply {
        moveTo(7f * s, 8.5f * s)
        lineTo(17f * s, 8.5f * s)
        lineTo(17f * s, 12.5f * s)
        cubicTo(17f * s, 15.5f * s, 14.5f * s, 16.8f * s, 12f * s, 16.8f * s)
        cubicTo(9.5f * s, 16.8f * s, 7f * s, 15.5f * s, 7f * s, 12.5f * s)
        close()
    }
    drawPath(body, color, style = stroke)
    drawLine(color, Offset(12f * s, 16.8f * s), Offset(12f * s, 21f * s), stroke.width, StrokeCap.Round)
}

private fun DrawScope.drawBed(s: Float, color: Color, stroke: Stroke) {
    drawLine(color, Offset(3f * s, 6.5f * s), Offset(3f * s, 19.5f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(21f * s, 12f * s), Offset(21f * s, 19.5f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(3f * s, 15.5f * s), Offset(21f * s, 15.5f * s), stroke.width, StrokeCap.Round)
    drawRoundRect(
        color = color,
        topLeft = Offset(5.5f * s, 10.8f * s),
        size = Size(5.5f * s, 4.7f * s),
        cornerRadius = CornerRadius(1.4f * s, 1.4f * s),
        style = stroke,
    )
    drawRoundRect(
        color = color,
        topLeft = Offset(11.2f * s, 12.0f * s),
        size = Size(9.8f * s, 3.5f * s),
        cornerRadius = CornerRadius(1.4f * s, 1.4f * s),
        style = stroke,
    )
}

private fun DrawScope.drawMusic(s: Float, color: Color, stroke: Stroke) {
    drawLine(color, Offset(9.5f * s, 17.5f * s), Offset(9.5f * s, 6.2f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(18.5f * s, 15.8f * s), Offset(18.5f * s, 4.5f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(9.5f * s, 6.2f * s), Offset(18.5f * s, 4.5f * s), stroke.width * 1.2f, StrokeCap.Round)
    drawCircle(color, radius = 2.6f * s, center = Offset(7.4f * s, 17.8f * s), style = stroke)
    drawCircle(color, radius = 2.6f * s, center = Offset(16.4f * s, 16.0f * s), style = stroke)
}

private fun DrawScope.drawDoor(s: Float, color: Color, stroke: Stroke) {
    drawRoundRect(
        color = color,
        topLeft = Offset(6f * s, 3.5f * s),
        size = Size(12f * s, 17f * s),
        cornerRadius = CornerRadius(1.5f * s, 1.5f * s),
        style = stroke,
    )
    drawLine(color, Offset(4f * s, 20.5f * s), Offset(20f * s, 20.5f * s), stroke.width, StrokeCap.Round)
    drawCircle(color, radius = 1.2f * s, center = Offset(14.8f * s, 12f * s))
}

private fun DrawScope.drawBell(s: Float, color: Color, stroke: Stroke) {
    val bell = Path().apply {
        moveTo(12f * s, 4f * s)
        cubicTo(8f * s, 4f * s, 6.5f * s, 7f * s, 6.5f * s, 11.5f * s)
        lineTo(5f * s, 16.5f * s)
        lineTo(19f * s, 16.5f * s)
        lineTo(17.5f * s, 11.5f * s)
        cubicTo(17.5f * s, 7f * s, 16f * s, 4f * s, 12f * s, 4f * s)
        close()
    }
    drawPath(bell, color, style = stroke)
    drawArc(
        color = color,
        startAngle = 15f,
        sweepAngle = 150f,
        useCenter = false,
        topLeft = Offset(9.8f * s, 17.2f * s),
        size = Size(4.4f * s, 3.8f * s),
        style = stroke,
    )
}

private fun DrawScope.drawSnowflake(s: Float, color: Color, stroke: Stroke) {
    val center = Offset(12f * s, 12f * s)
    for (angle in listOf(0f, 60f, 120f)) {
        rotate(angle, center) {
            drawLine(color, Offset(12f * s, 3.8f * s), Offset(12f * s, 20.2f * s), stroke.width, StrokeCap.Round)
            drawLine(color, Offset(12f * s, 6.5f * s), Offset(9.8f * s, 4.8f * s), stroke.width * 0.85f, StrokeCap.Round)
            drawLine(color, Offset(12f * s, 6.5f * s), Offset(14.2f * s, 4.8f * s), stroke.width * 0.85f, StrokeCap.Round)
            drawLine(color, Offset(12f * s, 17.5f * s), Offset(9.8f * s, 19.2f * s), stroke.width * 0.85f, StrokeCap.Round)
            drawLine(color, Offset(12f * s, 17.5f * s), Offset(14.2f * s, 19.2f * s), stroke.width * 0.85f, StrokeCap.Round)
        }
    }
}

private fun DrawScope.drawFlame(s: Float, color: Color, stroke: Stroke) {
    val flame = Path().apply {
        moveTo(12f * s, 3.5f * s)
        cubicTo(15.5f * s, 7.5f * s, 18.5f * s, 10.5f * s, 18.5f * s, 14.5f * s)
        cubicTo(18.5f * s, 18.2f * s, 15.6f * s, 20.5f * s, 12f * s, 20.5f * s)
        cubicTo(8.4f * s, 20.5f * s, 5.5f * s, 18.2f * s, 5.5f * s, 14.5f * s)
        cubicTo(5.5f * s, 10.5f * s, 8.5f * s, 7.5f * s, 12f * s, 3.5f * s)
        close()
    }
    drawPath(flame, color, style = stroke)
    val inner = Path().apply {
        moveTo(12f * s, 11.5f * s)
        cubicTo(13.8f * s, 13.5f * s, 14.6f * s, 14.8f * s, 14.6f * s, 16.5f * s)
        cubicTo(14.6f * s, 18.0f * s, 13.4f * s, 19.0f * s, 12f * s, 19.0f * s)
        cubicTo(10.6f * s, 19.0f * s, 9.4f * s, 18.0f * s, 9.4f * s, 16.5f * s)
        cubicTo(9.4f * s, 14.8f * s, 10.2f * s, 13.5f * s, 12f * s, 11.5f * s)
        close()
    }
    drawPath(inner, color)
}

private fun DrawScope.drawRadio(s: Float, color: Color, stroke: Stroke) {
    drawLine(color, Offset(6f * s, 8.5f * s), Offset(17.5f * s, 4f * s), stroke.width, StrokeCap.Round)
    drawRoundRect(
        color = color,
        topLeft = Offset(3.5f * s, 8.5f * s),
        size = Size(17f * s, 11.5f * s),
        cornerRadius = CornerRadius(2.2f * s, 2.2f * s),
        style = stroke,
    )
    drawCircle(color, radius = 2.6f * s, center = Offset(8.5f * s, 14.2f * s), style = stroke)
    drawLine(color, Offset(13.8f * s, 12.5f * s), Offset(17.8f * s, 12.5f * s), stroke.width, StrokeCap.Round)
    drawLine(color, Offset(13.8f * s, 16.0f * s), Offset(17.8f * s, 16.0f * s), stroke.width, StrokeCap.Round)
}
