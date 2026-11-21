package cl.magnesense.access

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import androidx.compose.ui.graphics.toArgb
import cl.magnesense.ui.theme.Palette

/**
 * Capa de pantalla completa del cursor por barrido: la linea que recorre, la ya fijada,
 * y en la confirmacion una mira con un anillo de cuenta regresiva. No recibe toques.
 */
class CursorOverlay(context: Context) : View(context) {

    var frame: ScanFrame = ScanFrame(ScanPhase.IDLE)
        set(value) {
            field = value
            invalidate()
        }

    private val density = resources.displayMetrics.density
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.Highlight.toArgb()
        strokeWidth = 4 * density
    }
    private val glow = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.Highlight.copy(alpha = 0.25f).toArgb()
        strokeWidth = 18 * density
    }
    private val halo = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.Highlight.copy(alpha = 0.25f).toArgb()
        style = Paint.Style.FILL
    }
    private val fixed = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.Text.copy(alpha = 0.55f).toArgb()
        strokeWidth = 2 * density
    }
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.Highlight.toArgb()
        style = Paint.Style.STROKE
        strokeWidth = 5 * density
        strokeCap = Paint.Cap.ROUND
    }
    private val label = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.Text.toArgb()
        textSize = 18 * density
        textAlign = Paint.Align.CENTER
        isFakeBoldText = true
    }
    private val labelBack = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.Background.copy(alpha = 0.9f).toArgb()
    }

    override fun onDraw(canvas: Canvas) {
        val f = frame
        val w = width.toFloat()
        val h = height.toFloat()
        when (f.phase) {
            ScanPhase.IDLE -> return
            ScanPhase.SWEEP_X -> {
                vertical(canvas, f.x * w, h, glow)
                vertical(canvas, f.x * w, h, line)
                caption(canvas, w, h, "Pulso cuando la línea esté sobre el botón")
            }
            ScanPhase.SWEEP_Y -> {
                f.fixedX?.let { vertical(canvas, it * w, h, fixed) }
                horizontal(canvas, f.y * h, w, glow)
                horizontal(canvas, f.y * h, w, line)
                caption(canvas, w, h, "Ahora la fila: pulso sobre el botón")
            }
            ScanPhase.CONFIRM -> {
                val cx = f.x * w
                val cy = f.y * h
                vertical(canvas, cx, h, fixed)
                horizontal(canvas, cy, w, fixed)
                val r = 28 * density
                canvas.drawCircle(cx, cy, r, halo)
                val sweep = 360f * f.confirmFraction.coerceIn(0f, 1f)
                canvas.drawArc(RectF(cx - r, cy - r, cx + r, cy + r), -90f, sweep, false, ring)
                canvas.drawCircle(cx, cy, 4 * density, line)
                caption(canvas, w, h, "Pulso para tocar · espera para cancelar")
            }
        }
    }

    private fun vertical(c: Canvas, x: Float, h: Float, p: Paint) = c.drawLine(x, 0f, x, h, p)

    private fun horizontal(c: Canvas, y: Float, w: Float, p: Paint) = c.drawLine(0f, y, w, y, p)

    private fun caption(c: Canvas, w: Float, h: Float, text: String) {
        val y = h - 120 * density
        val half = label.measureText(text) / 2 + 16 * density
        c.drawRoundRect(RectF(w / 2 - half, y - 30 * density, w / 2 + half, y + 14 * density), 20 * density, 20 * density, labelBack)
        c.drawText(text, w / 2, y, label)
    }
}
