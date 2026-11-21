package cl.magnesense.access

import cl.magnesense.pulses.PulseAction
import cl.magnesense.pulses.PulseProfile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneControlTest {

    private val done = mutableListOf<PhoneAction>()
    private val actuator = PhoneActuator { done += it; true }

    @Test
    fun withoutServiceNothingHappens() {
        assertEquals(PhoneResult.NOT_ENABLED, PhoneGate().perform(PhoneAction.NEXT, 0, null))
    }

    @Test
    fun rateLimitsBounces() {
        val gate = PhoneGate(minIntervalMs = 600)
        assertEquals(PhoneResult.DONE, gate.perform(PhoneAction.NEXT, 1_000, actuator))
        assertEquals(PhoneResult.TOO_SOON, gate.perform(PhoneAction.NEXT, 1_300, actuator))
        assertEquals(PhoneResult.DONE, gate.perform(PhoneAction.BACK, 1_700, actuator))
        assertEquals(listOf(PhoneAction.NEXT, PhoneAction.BACK), done)
    }

    @Test
    fun failedGestureIsReported() {
        assertEquals(PhoneResult.FAILED, PhoneGate().perform(PhoneAction.HOME, 0) { false })
    }

    @Test
    fun phoneProfileMapsTheAgreedCodes() {
        val table = PulseProfile.PHONE.commands.associate { it.code to it.action }
        assertEquals(PulseAction.NEXT, table["."])
        assertEquals(PulseAction.PREVIOUS, table[".."])
        assertEquals(PulseAction.BACK, table["-"])
        assertEquals(PulseAction.HOME, table["--"])
        assertEquals(PulseAction.OPEN_APP, table[".-"])
        assertEquals(PulseAction.ALARM, table["..."])
    }

    @Test
    fun noProfileHasDuplicateCodes() {
        for (p in PulseProfile.entries) {
            val codes = p.commands.map { it.code }
            assertTrue("${p.name}: $codes", codes.size == codes.toSet().size)
        }
    }
}
