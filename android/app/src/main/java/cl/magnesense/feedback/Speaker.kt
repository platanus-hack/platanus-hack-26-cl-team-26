package cl.magnesense.feedback

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

/**
 * Voz en espanol (es-CL, o cualquier espanol disponible). Lo que se pide antes de que
 * el motor este listo se guarda y se dice al terminar de iniciar.
 */
class Speaker(context: Context) : TextToSpeech.OnInitListener {

    private val tts = TextToSpeech(context.applicationContext, this)
    private val pending = ArrayList<Pair<String, Boolean>>()
    private var ready = false

    @Volatile
    var enabled = true

    override fun onInit(status: Int) {
        if (status != TextToSpeech.SUCCESS) return
        val chile = Locale.forLanguageTag("es-CL")
        val result = tts.setLanguage(chile)
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            tts.setLanguage(Locale.forLanguageTag("es"))
        }
        tts.setSpeechRate(1.05f)
        synchronized(this) {
            ready = true
            pending.forEach { (text, queue) -> say(text, queue) }
            pending.clear()
        }
    }

    /** [queue] = false interrumpe lo que se este diciendo (util al escanear). */
    @Synchronized
    fun speak(text: String, queue: Boolean = false) {
        if (!enabled) return
        if (!ready) {
            if (!queue) pending.clear()
            pending += text to queue
            return
        }
        say(text, queue)
    }

    private fun say(text: String, queue: Boolean) {
        tts.speak(text, if (queue) TextToSpeech.QUEUE_ADD else TextToSpeech.QUEUE_FLUSH, null, text.hashCode().toString())
    }

    fun shutdown() = tts.shutdown()
}
