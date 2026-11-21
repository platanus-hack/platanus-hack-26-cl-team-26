package cl.magnesense.ui.intro

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import cl.magnesense.MagneSenseApp
import cl.magnesense.gate.GatePhase
import cl.magnesense.gate.GateState
import cl.magnesense.gate.MagnetGate
import cl.magnesense.feedback.Haptics
import cl.magnesense.scanning.FeedbackKind
import cl.magnesense.sensor.SensorHub
import cl.magnesense.ui.theme.Palette
import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Intro "puerta magnetica": un circulo pide acercar el iman. Con el iman cerca salen del
 * circulo las lineas de campo de un dipolo y ondas, y un anillo se llena; al completarse,
 * se entra a la app. Todo dibujado en vectores (Canvas).
 */
@Composable
fun MagnetGateScreen(app: MagneSenseApp, onEnter: () -> Unit) {
    val context = LocalContext.current
    val gate = remember { MagnetGate() }
    val haptics = remember { Haptics(context) }
    var state by remember { mutableStateOf(GateState()) }
    var time by remember { mutableFloatStateOf(0f) }
    /** Intensidad visual suavizada (las lineas no parpadean con el ruido). */
    var glow by remember { mutableFloatStateOf(0f) }
    /** 0..1: animacion de salida. */
    var exit by remember { mutableFloatStateOf(0f) }
    var noSensor by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        app.speaker.speak("Acerca el imán para entrar")
        var start = -1L
        while (true) {
            var finished = false
            withFrameNanos { now ->
                if (start < 0) start = now
                val t = (now - start) / 1e9
                time = t.toFloat()
                val s = SensorHub.snapshot.value
                if (t > NO_SENSOR_AFTER_S && s.magRateHz <= 0.0) {
                    noSensor = true
                    finished = true
                } else {
                    state = gate.update(t, s.mag, s.gyro)
                    glow += (state.strength.toFloat() - glow) * 0.08f
                    finished = state.phase == GatePhase.DONE
                }
            }
            if (finished) break
        }
        haptics.play(FeedbackKind.SELECTED)
        app.speaker.speak(if (noSensor) "Entrando" else "Bienvenido")
        if (noSensor) kotlinx.coroutines.delay(1500)
        var start2 = -1L
        while (exit < 1f) {
            withFrameNanos { now ->
                if (start2 < 0) start2 = now
                exit = ((now - start2) / 1e9 / EXIT_S).toFloat().coerceIn(0f, 1f)
                time += 1f / 60
            }
        }
        onEnter()
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(Palette.Background)
            .graphicsLayer { alpha = 1f - exit },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val center = Offset(size.width / 2, size.height / 2)
            val radius = min(size.width, size.height) * 0.2f * (1f + exit * 0.5f)
            val charging = state.phase == GatePhase.CHARGING || state.phase == GatePhase.DONE
            drawFieldLines(center, radius, glow, time)
            if (charging || glow > 0.05f) drawRipples(center, radius, glow.coerceAtLeast(if (charging) 0.4f else 0f), time)
            val breathe = if (charging) 1f else 1f + 0.03f * sin(2 * PI.toFloat() * time / 2.4f)
            drawCore(center, radius * breathe, charging)
            drawProgressRing(center, radius + 22.dp.toPx(), state.progress.toFloat(), exit)
        }
        Column(
            Modifier.fillMaxSize().padding(top = 72.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("MagneSense", style = MaterialTheme.typography.displayMedium, color = Palette.Text)
        }
        Text(
            when {
                noSensor -> "Este teléfono no entrega el magnetómetro: entrando…"
                state.phase == GatePhase.DONE -> "¡Listo!"
                state.phase == GatePhase.CHARGING -> "Mantén el imán cerca…"
                else -> "Acerca el imán para entrar"
            },
            style = MaterialTheme.typography.titleLarge,
            color = Palette.Text,
            textAlign = TextAlign.Center,
            modifier = Modifier.width(180.dp),
        )
        Column(
            Modifier.fillMaxSize().padding(bottom = 64.dp),
            verticalArrangement = Arrangement.Bottom,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (state.phase == GatePhase.MEASURING && !noSensor) {
                Text("Midiendo el campo… deja el celular quieto", style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
            }
        }
    }
}

/**
 * Lineas de campo de un dipolo vertical: r = L·sin²θ (la forma de las limaduras de hierro).
 * Salen del borde del circulo, crecen con la intensidad y "fluyen" con un trazo discontinuo.
 */
private fun DrawScope.drawFieldLines(center: Offset, radius: Float, intensity: Float, time: Float) {
    if (intensity < 0.01f) return
    val scales = floatArrayOf(1.5f, 2.1f, 2.9f, 3.9f, 5.2f)
    val dash = PathEffect.dashPathEffect(floatArrayOf(28f, 18f), phase = -time * 90f)
    scales.forEachIndexed { i, k ->
        // Las lineas exteriores aparecen despues, a medida que sube la intensidad.
        val grow = ((intensity * scales.size * 1.2f) - i).coerceIn(0f, 1f)
        if (grow <= 0f) return@forEachIndexed
        for (side in intArrayOf(1, -1)) {
            val full = dipoleLine(center, radius, k * radius, side)
            val measure = PathMeasure().apply { setPath(full, false) }
            val partial = Path()
            measure.getSegment(0f, measure.length * grow, partial, true)
            drawPath(
                partial,
                Palette.Highlight.copy(alpha = (0.2f + 0.6f * grow) * (1f - i * 0.1f)),
                style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round, pathEffect = dash),
            )
        }
    }
}

/** Una linea de campo desde el polo norte (arriba) al sur, por el lado [side] (1 = derecha). */
private fun dipoleLine(center: Offset, radius: Float, l: Float, side: Int): Path {
    val theta0 = asin(sqrt(radius / l))
    val path = Path()
    val steps = 80
    for (s in 0..steps) {
        val theta = theta0 + (PI.toFloat() - 2 * theta0) * s / steps
        val r = l * sin(theta) * sin(theta)
        val x = center.x + side * r * sin(theta)
        val y = center.y - r * cos(theta)
        if (s == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    return path
}

/** Ondas que se expanden desde el circulo y se desvanecen. */
private fun DrawScope.drawRipples(center: Offset, radius: Float, intensity: Float, time: Float) {
    for (k in 0 until 3) {
        val phase = ((time / RIPPLE_PERIOD_S) + k / 3f) % 1f
        drawCircle(
            Palette.Highlight.copy(alpha = (1f - phase) * 0.5f * intensity),
            radius = radius * (1f + phase * 1.4f),
            center = center,
            style = Stroke(width = (4f * (1f - phase) + 1f).dp.toPx()),
        )
    }
}

private fun DrawScope.drawCore(center: Offset, radius: Float, active: Boolean) {
    drawCircle(Palette.Surface, radius = radius, center = center)
    drawCircle(
        if (active) Palette.Highlight else Palette.Border,
        radius = radius,
        center = center,
        style = Stroke(width = 4.dp.toPx()),
    )
}

/** Anillo de carga con un halo suave debajo. */
private fun DrawScope.drawProgressRing(center: Offset, radius: Float, progress: Float, exit: Float) {
    val topLeft = Offset(center.x - radius, center.y - radius)
    val box = Size(radius * 2, radius * 2)
    drawCircle(Palette.Border.copy(alpha = 0.6f), radius = radius, center = center, style = Stroke(width = 10.dp.toPx()))
    if (progress <= 0f) return
    val sweep = 360f * progress
    drawArc(
        Palette.Highlight.copy(alpha = 0.22f + 0.3f * exit),
        startAngle = -90f,
        sweepAngle = sweep,
        useCenter = false,
        topLeft = topLeft,
        size = box,
        style = Stroke(width = (26 + 30 * exit).dp.toPx(), cap = StrokeCap.Round),
    )
    drawArc(
        Palette.Highlight,
        startAngle = -90f,
        sweepAngle = sweep,
        useCenter = false,
        topLeft = topLeft,
        size = box,
        style = Stroke(width = 10.dp.toPx(), cap = StrokeCap.Round),
    )
}

private const val NO_SENSOR_AFTER_S = 3.0
private const val EXIT_S = 0.6
private const val RIPPLE_PERIOD_S = 0.7f
