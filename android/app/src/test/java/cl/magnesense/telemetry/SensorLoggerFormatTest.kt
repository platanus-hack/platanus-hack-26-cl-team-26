package cl.magnesense.telemetry

import cl.magnesense.detector.Vec3
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SensorLoggerFormatTest {

    @Test
    fun batchMatchesSensorLoggerHttpPush() {
        val json = SensorLoggerFormat.batch(
            messageId = 7,
            sessionId = "s1",
            deviceId = "phone",
            uncalibrated = true,
            samples = listOf(
                SensorSample(1_700_000_000_000_000_000, Vec3(20.0, -5.5, -40.25)),
                SensorSample(1_700_000_000_010_000_000, Vec3(21.0, -5.0, -40.0)),
            ),
        )
        assertEquals(
            "{\"messageId\":7,\"sessionId\":\"s1\",\"deviceId\":\"phone\",\"payload\":[" +
                "{\"name\":\"magnetometeruncalibrated\",\"time\":1700000000000000000," +
                "\"values\":{\"x\":20.0000,\"y\":-5.5000,\"z\":-40.2500}}," +
                "{\"name\":\"magnetometeruncalibrated\",\"time\":1700000000010000000," +
                "\"values\":{\"x\":21.0000,\"y\":-5.0000,\"z\":-40.0000}}]}",
            json,
        )
    }

    @Test
    fun gyroscopeSamplesUseSensorLoggerName() {
        val json = SensorLoggerFormat.batch(
            1, "s", "d", uncalibrated = true,
            samples = listOf(SensorSample(5, Vec3(0.1, 0.0, -0.2), gyroscope = true), SensorSample(6, Vec3.ZERO)),
        )
        assertTrue(json.contains("{\"name\":\"gyroscope\",\"time\":5,\"values\":{\"x\":0.1000,\"y\":0.0000,\"z\":-0.2000}}"))
        assertTrue(json.contains("{\"name\":\"magnetometeruncalibrated\",\"time\":6,"))
    }

    @Test
    fun calibratedSensorUsesPlainName() {
        val json = SensorLoggerFormat.batch(1, "s", "d", uncalibrated = false, samples = listOf(SensorSample(1, Vec3.ZERO)))
        assertTrue(json.contains("\"name\":\"magnetometer\""))
    }

    @Test
    fun eventEscapesTextAndSkipsMissingNumbers() {
        val json = SensorLoggerFormat.event("selected", "Luz \"sala\"", 123, signal = 12.5, cosine = Double.NaN)
        assertEquals("{\"type\":\"selected\",\"text\":\"Luz \\\"sala\\\"\",\"time\":123,\"signal\":12.5000}", json)
    }
}
