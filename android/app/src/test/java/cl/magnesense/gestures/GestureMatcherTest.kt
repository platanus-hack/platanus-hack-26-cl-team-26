package cl.magnesense.gestures

import cl.magnesense.remote.DetectorType
import cl.magnesense.remote.RemoteDetector
import cl.magnesense.remote.ServerEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GestureMatcherTest {

    private fun event(trigger: String) = RemoteDetector("izq", DetectorType.EVENT, trigger, active = false, count = 0)
    private fun ev(kind: String, state: String? = null, detector: String = "izq") = ServerEvent(detector, kind, 1.0, state)

    @Test
    fun eventWithAnyFiresOnStartOnly() {
        val d = event("any")
        assertTrue(GestureMatcher.fires(d, ev("start")))
        assertFalse(GestureMatcher.fires(d, ev("end")))
        assertFalse(GestureMatcher.fires(d, ev("short")))
        assertFalse(GestureMatcher.fires(d, ev("drift")))
    }

    @Test
    fun eventWithSpecificTriggerFiresOnThatKind() {
        for (trigger in listOf("short", "long", "double")) {
            val d = event(trigger)
            val fired = listOf("start", "end", "short", "long", "double").filter { GestureMatcher.fires(d, ev(it)) }
            assertEquals(listOf(trigger), fired)
        }
    }

    @Test
    fun blankEventTriggerBehavesLikeAny() {
        assertTrue(GestureMatcher.fires(event(""), ev("start")))
    }

    @Test
    fun rhythmFiresWhenItPauses() {
        val d = RemoteDetector("resp", DetectorType.RHYTHM, "pause", active = false, count = 0)
        assertTrue(GestureMatcher.fires(d, ev("pause", detector = "resp")))
        assertFalse(GestureMatcher.fires(d, ev("resume", detector = "resp")))
        assertFalse(GestureMatcher.fires(d, ev("rhythm_start", detector = "resp")))
    }

    @Test
    fun stateFiresWhenEnteringTheChosenLabel() {
        val d = RemoteDetector("mano", DetectorType.STATE, "abierta", active = false, count = 0, labels = listOf("abierta", "cerrada"))
        assertTrue(GestureMatcher.fires(d, ev("state", "abierta", "mano")))
        assertFalse(GestureMatcher.fires(d, ev("state", "cerrada", "mano")))
    }

    @Test
    fun eventsFromOtherDetectorsNeverFire() {
        assertFalse(GestureMatcher.fires(event("any"), ev("start", detector = "otro")))
    }
}
