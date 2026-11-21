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
                MagSample(1_700_000_000_000_000_000, Vec3(20.0, -5.5, -40.25)),
                MagSample(1_700_000_000_010_000_000, Vec3(21.0, -5.0, -40.0)),
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
    fun calibratedSensorUsesPlainName() {
        val json = SensorLoggerFormat.batch(1, "s", "d", uncalibrated = false, samples = listOf(MagSample(1, Vec3.ZERO)))
        assertTrue(json.contains("\"name\":\"magnetometer\""))
    }

    @Test
    fun eventEscapesTextAndSkipsMissingNumbers() {
        val json = SensorLoggerFormat.event("selected", "Luz \"sala\"", 123, signal = 12.5, cosine = Double.NaN)
        assertEquals("{\"type\":\"selected\",\"text\":\"Luz \\\"sala\\\"\",\"time\":123,\"signal\":12.5000}", json)
    }
}
