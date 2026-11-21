package cl.magnesense.data

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Registro tecnico para encontrar errores: cada gesto con su fuerza, umbral y direccion, cada
 * descarte, calibracion, ejemplo grabado, accion y error (tambien los cierres inesperados).
 * Va a un archivo (se puede compartir desde Historial) y a logcat con la etiqueta "MagneSense".
 */
class DiagLog(context: Context) {

    private val file = File(context.filesDir, FILE_NAME)
    private val old = File(context.filesDir, "$FILE_NAME.1")
    private val format = SimpleDateFormat("dd/MM HH:mm:ss.SSS", Locale.US)

    @Synchronized
    fun add(text: String) {
        Log.i(TAG, text)
        runCatching {
            if (file.length() > MAX_BYTES) {
                old.delete()
                file.renameTo(old)
            }
            file.appendText("${format.format(Date())}  $text\n")
        }
    }

    /** Las ultimas lineas, de la mas vieja a la mas nueva. */
    @Synchronized
    fun tail(maxChars: Int = SHARE_CHARS): String {
        val all = runCatching { (if (old.exists()) old.readText() else "") + (if (file.exists()) file.readText() else "") }
            .getOrDefault("")
        return if (all.length <= maxChars) all else all.substring(all.indexOf('\n', all.length - maxChars) + 1)
    }

    @Synchronized
    fun clear() {
        file.delete()
        old.delete()
    }

    /** Anota los cierres inesperados antes de que Android cierre la app. */
    fun catchCrashes() {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, e ->
            add("ERROR: la app se cerró (${thread.name}): ${Log.getStackTraceString(e).take(4_000)}")
            previous?.uncaughtException(thread, e)
        }
    }

    private companion object {
        const val TAG = "MagneSense"
        const val FILE_NAME = "diag.log"
        const val MAX_BYTES = 400_000L
        /** Un Intent de texto no aguanta mucho mas. */
        const val SHARE_CHARS = 150_000
    }
}
