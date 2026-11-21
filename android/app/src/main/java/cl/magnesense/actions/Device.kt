package cl.magnesense.actions

import cl.magnesense.scanning.ScanOption

enum class DeviceKind { SWITCH, CAREGIVER }

/**
 * Un dispositivo controlable. Para enchufes tipo Shelly:
 * ON  = http://IP/relay/0?turn=on, OFF = http://IP/relay/0?turn=off.
 * Si las URL estan vacias funciona en modo demostracion (solo cambia en pantalla).
 */
data class Device(
    val id: String,
    val name: String,
    val icon: String,
    val kind: DeviceKind = DeviceKind.SWITCH,
    val onUrl: String = "",
    val offUrl: String = "",
) {
    val isCaregiver: Boolean get() = kind == DeviceKind.CAREGIVER

    fun toScanOption() = ScanOption(
        id = id,
        label = name,
        critical = isCaregiver,
        confirmPrompt = if (isCaregiver) "¿Llamar a tu cuidador?" else "¿$name?",
    )

    companion object {
        val DEFAULTS = listOf(
            Device("luz", "Luz", "bulb"),
            Device("ventilador", "Ventilador", "fan"),
            Device("tv", "Televisión", "tv"),
            Device("cuidador", "Llamar cuidador", "phone", DeviceKind.CAREGIVER),
        )

        /** Claves de iconos vectoriales para elegir en ajustes. */
        val ICONS = listOf("bulb", "fan", "tv", "phone", "plug", "bed", "music", "door", "bell", "ac", "heater", "radio")
    }
}
