package cl.magnesense.sensor

import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.SystemClock
import cl.magnesense.detector.RateMeter
import cl.magnesense.detector.Vec3

/**
 * Registra el magnetometro (sin calibrar si existe) y el giroscopio a 200 Hz y reenvia
 * cada muestra a [SensorHub.sink]. Publica un resumen para la interfaz ~30 veces por segundo.
 */
class SensorReader(private val sensorManager: SensorManager, private val handler: Handler) :
    SensorEventListener {

    private val magSensor: Sensor? =
        sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD_UNCALIBRATED)
            ?: sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
    private val gyroSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    private val magRate = RateMeter()
    private val gyroRate = RateMeter()
    private var snapshot = SensorSnapshot()
    private var lastPublishNanos = 0L

    fun start() {
        val mag = magSensor ?: return
        snapshot = SensorSnapshot(
            running = true,
            magSensorName = mag.name,
            magUncalibrated = mag.type == Sensor.TYPE_MAGNETIC_FIELD_UNCALIBRATED,
            magMaxRange = mag.maximumRange.toDouble(),
            gyroAvailable = gyroSensor != null,
        )
        handler.post { SensorHub.sink?.onSensorsStarted(snapshot.magMaxRange, snapshot.gyroAvailable) }
        sensorManager.registerListener(this, mag, SAMPLING_PERIOD_US, handler)
        gyroSensor?.let { sensorManager.registerListener(this, it, SAMPLING_PERIOD_US, handler) }
        SensorHub.publish(snapshot)
    }

    fun stop() {
        sensorManager.unregisterListener(this)
        magRate.reset()
        gyroRate.reset()
        SensorHub.publish(snapshot.copy(running = false, magRateHz = 0.0, gyroRateHz = 0.0))
    }

    override fun onSensorChanged(event: SensorEvent) {
        val v = event.values
        val value = Vec3(v[0].toDouble(), v[1].toDouble(), v[2].toDouble())
        val t = event.timestamp
        when (event.sensor.type) {
            Sensor.TYPE_MAGNETIC_FIELD_UNCALIBRATED -> {
                // values[3..5] es el sesgo estimado: restarlo da el campo "real".
                val bias = Vec3(v[3].toDouble(), v[4].toDouble(), v[5].toDouble())
                onMag(t, value, (value - bias).norm)
            }
            Sensor.TYPE_MAGNETIC_FIELD -> onMag(t, value, value.norm)
            Sensor.TYPE_GYROSCOPE -> {
                gyroRate.tick(t / 1e9)
                snapshot = snapshot.copy(gyro = value, gyroRateHz = gyroRate.rateHz)
                SensorHub.sink?.onGyroscope(t, value)
            }
        }
        maybePublish()
    }

    private fun onMag(t: Long, value: Vec3, earthField: Double) {
        magRate.tick(t / 1e9)
        snapshot = snapshot.copy(mag = value, earthField = earthField, magRateHz = magRate.rateHz)
        SensorHub.sink?.onMagnetometer(t, value)
    }

    private fun maybePublish() {
        val now = SystemClock.elapsedRealtimeNanos()
        if (now - lastPublishNanos >= PUBLISH_PERIOD_NS) {
            lastPublishNanos = now
            SensorHub.publish(snapshot)
        }
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) = Unit

    private companion object {
        /** 5 ms = 200 Hz, el maximo que Android permite sin el limite de privacidad. */
        const val SAMPLING_PERIOD_US = 5_000
        const val PUBLISH_PERIOD_NS = 33_000_000L
    }
}
