package cl.magnesense.feedback

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import cl.magnesense.scanning.FeedbackKind

/** Sonido corto + vibracion para confirmar lo que paso sin mirar la pantalla. */
class Haptics(context: Context) {

    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        context.getSystemService(VibratorManager::class.java)?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Vibrator::class.java)
    }

    private val tones: ToneGenerator? = runCatching { ToneGenerator(AudioManager.STREAM_MUSIC, 70) }.getOrNull()

    fun play(kind: FeedbackKind) {
        when (kind) {
            FeedbackKind.ARMED -> {
                tone(ToneGenerator.TONE_PROP_BEEP, 120)
                vibrate(longArrayOf(0, 60))
            }
            FeedbackKind.SELECTED -> {
                tone(ToneGenerator.TONE_PROP_ACK, 200)
                vibrate(longArrayOf(0, 70, 80, 70))
            }
            FeedbackKind.CANCELLED -> {
                tone(ToneGenerator.TONE_PROP_NACK, 300)
                vibrate(longArrayOf(0, 300))
            }
        }
    }

    private fun tone(type: Int, ms: Int) {
        runCatching { tones?.startTone(type, ms) }
    }

    private fun vibrate(pattern: LongArray) {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        runCatching { v.vibrate(VibrationEffect.createWaveform(pattern, -1)) }
    }
}
