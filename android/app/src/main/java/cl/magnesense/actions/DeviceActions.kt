package cl.magnesense.actions

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class ActionResult(
    val deviceId: String,
    /** Frase corta que tambien se dice en voz alta, p. ej. "Encendiendo luz". */
    val message: String,
    val ok: Boolean,
    val timeMs: Long = System.currentTimeMillis(),
)

/** Configuracion del cuidador. */
data class CaregiverConfig(val phone: String = "", val webhookUrl: String = "")

/**
 * Ejecuta las acciones: alterna enchufes por HTTP y avisa al cuidador.
 * Los errores de red nunca botan la app: se informan como [ActionResult] con ok = false.
 */
class DeviceActions(private val context: Context) {

    private val _isOn = MutableStateFlow<Map<String, Boolean>>(emptyMap())
    val isOn: StateFlow<Map<String, Boolean>> = _isOn.asStateFlow()

    private val _lastResult = MutableStateFlow<ActionResult?>(null)
    val lastResult: StateFlow<ActionResult?> = _lastResult.asStateFlow()

    @Volatile
    var caregiver = CaregiverConfig()

    /** Ejecuta la accion principal del dispositivo (alternar o llamar al cuidador). */
    suspend fun run(device: Device): ActionResult =
        if (device.isCaregiver) callCaregiver(device) else setPower(device, !(isOn.value[device.id] ?: false))

    /** Prende o apaga. Con URL vacia cambia el estado en pantalla y (para Luz) la linterna real del celular. */
    suspend fun setPower(device: Device, on: Boolean): ActionResult {
        if (device.id == "luz" || device.icon == "bulb" || device.icon == "💡") {
            setPhoneTorch(on)
        }
        val url = if (on) device.onUrl else device.offUrl
        val verb = if (on) "Encendiendo" else "Apagando"
        val result = if (url.isBlank()) {
            ActionResult(device.id, "$verb ${device.name.lowercase()}", ok = true)
        } else {
            when (val r = Http.get(url)) {
                is Http.Result.Ok -> ActionResult(device.id, "$verb ${device.name.lowercase()}", ok = true)
                is Http.Result.Failed -> ActionResult(device.id, "No se pudo conectar con ${device.name}", ok = false)
                    .also { android.util.Log.w(TAG, "${device.name}: ${r.reason} ($url)") }
            }
        }
        if (result.ok) _isOn.update { it + (device.id to on) }
        _lastResult.value = result
        return result
    }

    /** Activa/desactiva el flash LED trasero del celular como actuador fisico inmediato en la demo. */
    private fun setPhoneTorch(on: Boolean) {
        try {
            val cm = context.getSystemService(CameraManager::class.java) ?: return
            val id = cm.cameraIdList.firstOrNull { cid ->
                cm.getCameraCharacteristics(cid).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            } ?: return
            cm.setTorchMode(id, on)
        } catch (e: Exception) {
            android.util.Log.w(TAG, "No se pudo cambiar la linterna del celular", e)
        }
    }

    /** Webhook (si hay) y luego llamada telefonica (o marcador si no hay permiso). */
    suspend fun callCaregiver(device: Device): ActionResult {
        val cfg = caregiver
        var notified = false
        if (cfg.webhookUrl.isNotBlank()) {
            val body = JSONObject()
                .put("event", "caregiver_call")
                .put("app", "MagneSense")
                .put("time", System.currentTimeMillis())
                .toString()
            notified = Http.postJson(cfg.webhookUrl, body) is Http.Result.Ok
        }
        val called = cfg.phone.isNotBlank() && withContext(Dispatchers.Main) { startCall(cfg.phone) }
        val result = when {
            called -> ActionResult(device.id, "Llamando a tu cuidador", ok = true)
            notified -> ActionResult(device.id, "Aviso enviado a tu cuidador", ok = true)
            cfg.phone.isBlank() && cfg.webhookUrl.isBlank() ->
                ActionResult(device.id, "Falta configurar el cuidador", ok = false)
            else -> ActionResult(device.id, "No se pudo avisar al cuidador", ok = false)
        }
        _lastResult.value = result
        return result
    }

    private fun startCall(phone: String): Boolean {
        val canCall = context.checkSelfPermission(Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED
        val intent = Intent(if (canCall) Intent.ACTION_CALL else Intent.ACTION_DIAL, Uri.parse("tel:$phone"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            true
        } catch (e: Exception) {
            android.util.Log.w(TAG, "No se pudo iniciar la llamada", e)
            false
        }
    }

    private companion object {
        const val TAG = "DeviceActions"
    }
}
