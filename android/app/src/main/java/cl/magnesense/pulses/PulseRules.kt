package cl.magnesense.pulses

import cl.magnesense.access.PhoneAction

/**
 * Cuando Pulsos puede actuar. Kotlin puro para probarlo sin Android.
 */
object PulseRules {

    /**
     * Pulsos actua si es el modo elegido, no se esta ensenando un gesto y no se esta
     * calibrando: en Calibrar, 3D, Debug o la intro el iman se mueve a proposito y esos
     * movimientos no deben deslizar, volver atras ni hacer sonar la alarma.
     */
    fun enabled(pulsesMode: Boolean, teaching: Boolean, inForeground: Boolean, magnetBusy: Boolean): Boolean =
        pulsesMode && !teaching && !(inForeground && magnetBusy)

    /** Las acciones del Modo celular son para otras apps: dentro de MagneSense solo "volver" tiene sentido. */
    fun phoneActionAllowed(action: PhoneAction, inForeground: Boolean): Boolean =
        !inForeground || action == PhoneAction.OPEN_APP
}
