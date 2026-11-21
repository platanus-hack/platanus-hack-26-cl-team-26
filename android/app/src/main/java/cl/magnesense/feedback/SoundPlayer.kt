package cl.magnesense.feedback

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/**
 * Sonidos locales de los gestos, sintetizados en la app (no hay archivos ni internet):
 * una cancion que se pone y se para, y un cuack de pato.
 */
class SoundPlayer {

    private val song: ShortArray by lazy(::synthSong)
    private val quack: ShortArray by lazy(::synthQuack)

    private var songTrack: AudioTrack? = null

    val songPlaying: Boolean
        @Synchronized get() = songTrack?.playState == AudioTrack.PLAYSTATE_PLAYING

    /** Pone la cancion en bucle, o la para si ya sonaba. Devuelve true si quedo sonando. */
    @Synchronized
    fun toggleSong(): Boolean {
        songTrack?.let {
            stop(it)
            songTrack = null
            return false
        }
        val track = staticTrack(song) ?: return false
        runCatching {
            track.setLoopPoints(0, song.size, -1)
            track.play()
        }
        songTrack = track
        return true
    }

    @Synchronized
    fun stopSong() {
        songTrack?.let(::stop)
        songTrack = null
    }

    fun quack() {
        val track = staticTrack(quack) ?: return
        runCatching {
            track.setNotificationMarkerPosition(quack.size - 1)
            track.setPlaybackPositionUpdateListener(object : AudioTrack.OnPlaybackPositionUpdateListener {
                override fun onMarkerReached(t: AudioTrack) = t.release()
                override fun onPeriodicNotification(t: AudioTrack) = Unit
            })
            track.play()
        }.onFailure { track.release() }
    }

    private fun stop(t: AudioTrack) {
        runCatching { t.stop() }
        t.release()
    }

    private fun staticTrack(pcm: ShortArray): AudioTrack? = runCatching {
        AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build(),
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build(),
            )
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(pcm.size * 2)
            .build()
            .also { it.write(pcm, 0, pcm.size) }
    }.getOrNull()

    private companion object {
        const val RATE = 22_050

        /** Melodia original y alegre (notas MIDI, 0 = silencio), en corcheas a 132 bpm. */
        val MELODY = intArrayOf(
            72, 76, 79, 76, 77, 74, 71, 74, 72, 76, 79, 84, 83, 79, 0, 0,
            81, 79, 77, 76, 74, 77, 76, 72, 74, 76, 74, 71, 72, 0, 0, 0,
        )
        val BASS = intArrayOf(48, 53, 55, 48, 53, 50, 43, 48)

        fun synthSong(): ShortArray {
            val step = 60.0 / 132 / 2
            val n = (MELODY.size * step * RATE).toInt()
            val out = ShortArray(n)
            val stepSamples = step * RATE
            for (i in 0 until n) {
                val t = i / RATE.toDouble()
                val k = (i / stepSamples).toInt()
                val local = (i - k * stepSamples) / RATE
                var v = 0.0
                val note = MELODY[k]
                if (note > 0) {
                    val f = midi(note)
                    val env = min(1.0, local / 0.01) * exp(-local * 5)
                    v += 0.35 * env * (sin(2 * PI * f * t) + 0.3 * sin(4 * PI * f * t))
                }
                val bk = (i / (stepSamples * 4)).toInt() % BASS.size
                val bLocal = (i - (i / (stepSamples * 4)).toInt() * stepSamples * 4) / RATE
                v += 0.25 * exp(-bLocal * 3) * sin(2 * PI * midi(BASS[bk]) * t)
                out[i] = (v.coerceIn(-1.0, 1.0) * 26_000).toInt().toShort()
            }
            return out
        }

        /** Dos "cuack": tono nasal que baja, con armonicos y vibrato rapido. */
        fun synthQuack(): ShortArray {
            val one = 0.22
            val gap = 0.08
            val n = ((2 * one + gap) * RATE).toInt()
            val out = ShortArray(n)
            var phase = 0.0
            for (i in 0 until n) {
                val t = i / RATE.toDouble()
                val local = if (t < one) t else t - one - gap
                if (local < 0 || local > one) continue
                val x = local / one
                val f = 520 - 260 * x + 25 * sin(2 * PI * 38 * local)
                phase += 2 * PI * f / RATE
                var v = 0.0
                for (h in 1..6) v += sin(h * phase) / h.toDouble().pow(0.8) * if (h in 2..3) 1.4 else 1.0
                val env = min(1.0, local / 0.015) * (1 - x).pow(0.6)
                out[i] = ((v * 0.22 * env).coerceIn(-1.0, 1.0) * 28_000).toInt().toShort()
            }
            return out
        }

        fun midi(n: Int) = 440.0 * 2.0.pow((n - 69) / 12.0)
    }
}
