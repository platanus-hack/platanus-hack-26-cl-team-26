package cl.magnesense.access

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.LinearLayout
import android.widget.TextView
import androidx.compose.ui.graphics.toArgb
import cl.magnesense.MagneSenseApp
import cl.magnesense.MainActivity
import cl.magnesense.data.ActivationMode
import cl.magnesense.pulses.PulseDecoder
import cl.magnesense.pulses.PulseInterp
import cl.magnesense.pulses.PulseLast
import cl.magnesense.pulses.PulseProfile
import cl.magnesense.pulses.PulseUiState
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Modo celular: con pulsos del iman se usa el telefono entero (deslizar videos, atras, inicio).
 *
 * Solo hace gestos y acciones globales seguras; no lee la pantalla (canRetrieveWindowContent
 * = false) ni toca puntos arbitrarios. Muestra una pastilla flotante, que no bloquea toques,
 * con los codigos y la ultima accion, mientras el perfil de Pulsos sea "Celular".
 */
class PhoneControlService : AccessibilityService() {

    private var scope: CoroutineScope? = null
    private var pill: LinearLayout? = null
    private var hint: TextView? = null
    private var flashJob: Job? = null
    private var lastSeen: PulseLast? = null

    // --- Cursor por barrido ---
    private val main = Handler(Looper.getMainLooper())
    private val scan = PointScan()
    private var cursorView: CursorOverlay? = null

    @Volatile
    private var cursorOn = false

    override fun onServiceConnected() {
        super.onServiceConnected()
        PhoneControl.actuator = PhoneActuator(::perform)
        PhoneControl.cursor = object : CursorInput {
            override val active: Boolean get() = cursorOn
            override fun pulse() {
                main.post(::onCursorPulse)
            }
        }
        showCursorLayer()
        showPill()
        val app = application as MagneSenseApp
        scope = MainScope().also { s ->
            s.launch { app.pulses.state.collect { render(app, it) } }
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onUnbind(intent: Intent?): Boolean {
        cleanUp()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        cleanUp()
        super.onDestroy()
    }

    private fun cleanUp() {
        if (PhoneControl.actuator != null) PhoneControl.actuator = null
        PhoneControl.cursor = null
        cursorOn = false
        scope?.cancel()
        scope = null
        cursorView?.let { runCatching { getSystemService(WindowManager::class.java).removeView(it) } }
        cursorView = null
        pill?.let { runCatching { getSystemService(WindowManager::class.java).removeView(it) } }
        pill = null
    }

    // --- Acciones ----------------------------------------------------------------

    private fun perform(action: PhoneAction): Boolean = when (action) {
        PhoneAction.NEXT -> swipe(up = true)
        PhoneAction.PREVIOUS -> swipe(up = false)
        PhoneAction.BACK -> performGlobalAction(GLOBAL_ACTION_BACK)
        PhoneAction.HOME -> performGlobalAction(GLOBAL_ACTION_HOME)
        PhoneAction.CURSOR -> main.post(::startCursor)
        PhoneAction.OPEN_APP -> runCatching {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
            )
        }.isSuccess
    }

    /** Deslizar vertical por el centro: hacia arriba = siguiente video / bajar la pagina. */
    private fun swipe(up: Boolean): Boolean {
        val m = resources.displayMetrics
        val x = m.widthPixels / 2f
        val from = m.heightPixels * if (up) 0.75f else 0.25f
        val to = m.heightPixels * if (up) 0.25f else 0.75f
        val path = Path().apply {
            moveTo(x, from)
            lineTo(x, to)
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, SWIPE_MS))
            .build()
        return dispatchGesture(gesture, null, null)
    }

    // --- Cursor por barrido -----------------------------------------------------------

    private fun showCursorLayer() {
        val view = CursorOverlay(this).apply { visibility = View.GONE }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        runCatching { getSystemService(WindowManager::class.java).addView(view, params) }
            .onSuccess { cursorView = view }
    }

    private fun startCursor() {
        val view = cursorView ?: return
        scan.start(now())
        cursorOn = true
        view.visibility = View.VISIBLE
        speak("Elige la columna")
        view.postOnAnimation(frameLoop)
    }

    private val frameLoop: Runnable = object : Runnable {
        override fun run() {
            val view = cursorView ?: return
            if (!cursorOn) return
            if (scan.tick(now()) == ScanOutcome.Cancelled) {
                endCursor("Cancelado")
                return
            }
            view.frame = scan.frame(now())
            view.postOnAnimation(this)
        }
    }

    private fun onCursorPulse() {
        if (!cursorOn) return
        when (val outcome = scan.pulse(now())) {
            is ScanOutcome.Tap -> {
                endCursor(null)
                // Esperar a que se oculte la capa antes de tocar.
                main.postDelayed({ tapAt(outcome.x, outcome.y) }, TAP_DELAY_MS)
            }
            else -> speak(
                when (scan.phase) {
                    ScanPhase.SWEEP_Y -> "Ahora la fila"
                    ScanPhase.CONFIRM -> "Pulso para tocar"
                    else -> return
                },
            )
        }
    }

    private fun endCursor(message: String?) {
        cursorOn = false
        scan.cancel()
        cursorView?.let {
            it.frame = ScanFrame(ScanPhase.IDLE)
            it.visibility = View.GONE
        }
        message?.let(::speak)
    }

    /** Toca el punto elegido (fracciones de la capa, que cubre toda la pantalla). */
    private fun tapAt(fx: Float, fy: Float) {
        val view = cursorView ?: return
        val origin = IntArray(2).also(view::getLocationOnScreen)
        val x = origin[0] + fx * view.width
        val y = origin[1] + fy * view.height
        val path = Path().apply { moveTo(x, y) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, TAP_MS))
            .build()
        dispatchGesture(gesture, null, null)
    }

    private fun speak(text: String) = (application as MagneSenseApp).speaker.speak(text)

    private fun now(): Double = SystemClock.uptimeMillis() / 1000.0

    // --- Pastilla flotante ----------------------------------------------------------

    private fun showPill() {
        val wm = getSystemService(WindowManager::class.java)
        val title = TextView(this).apply {
            text = "MagneSense · Modo celular"
            setTextColor(Palette.Muted.toArgb())
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        }
        val main = TextView(this).apply {
            setTextColor(Palette.Text.toArgb())
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
            typeface = Typeface.DEFAULT_BOLD
        }
        val view = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(18), dp(8), dp(18), dp(10))
            background = GradientDrawable().apply {
                cornerRadius = dp(24).toFloat()
                setColor(Palette.Background.copy(alpha = 0.92f).toArgb())
                setStroke(dp(1), Palette.Border.toArgb())
            }
            addView(title)
            addView(main)
            visibility = View.GONE
        }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = dp(56)
        }
        runCatching { wm.addView(view, params) }.onSuccess {
            pill = view
            hint = main
        }
    }

    private fun render(app: MagneSenseApp, s: PulseUiState) {
        val view = pill ?: return
        val text = hint ?: return
        val active = !app.inForeground &&
            s.profile == PulseProfile.PHONE &&
            s.interp == PulseInterp.COMMANDS &&
            app.settings.settings.value.activationMode == ActivationMode.PULSES
        view.visibility = if (active) View.VISIBLE else View.GONE
        if (!active) return

        val last = s.last
        if (last != null && last !== lastSeen) {
            lastSeen = last
            text.text = "${last.code}  ${last.text}"
            text.setTextColor((if (last.ok) Palette.Highlight else Palette.WarningSoft).toArgb())
            flashJob?.cancel()
            flashJob = scope?.launch {
                delay(FLASH_MS)
                showIdle(text, app.pulses.state.value)
            }
            return
        }
        if (flashJob?.isActive == true) return
        showIdle(text, s)
    }

    private fun showIdle(text: TextView, s: PulseUiState) {
        if (s.locked && s.symbols.isEmpty()) {
            text.text = LOCKED_HINT
            text.setTextColor(Palette.Muted.toArgb())
        } else if (s.symbols.isNotEmpty()) {
            text.text = PulseDecoder.pretty(s.symbols)
            text.setTextColor(Palette.Highlight.toArgb())
        } else {
            text.text = IDLE_HINT
            text.setTextColor(Palette.Text.toArgb())
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private companion object {
        const val SWIPE_MS = 250L
        const val TAP_MS = 60L
        const val TAP_DELAY_MS = 150L
        const val FLASH_MS = 1_500L
        const val IDLE_HINT = "• ▲   • • ▼   — ◁   — — ⌂   — • ⌖"
        const val LOCKED_HINT = "⏸ En pausa · • • • para activar"
    }
}
