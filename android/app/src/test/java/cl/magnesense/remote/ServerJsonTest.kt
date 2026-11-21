package cl.magnesense.remote

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Mensajes con la forma real de server.py / detectors.py (fase 2). */
class ServerJsonTest {

    private val dataMessage = """
        {"type":"data","calibrating":false,"signal":0.4,"recording":"",
         "examples":{"izquierda":5,"abierta":3},
         "phase2":{"calibrating":false,"noise":0.31,"sensor_noise":0.2,"gyro":true,"phone_moving":false,
           "detectors":[
             {"name":"izquierda","type":"event","active":false,"signal":0.2,"threshold":3.1,"count":2,
              "last":"short","direction":{"u":[1,0,0],"peak":12.0,"min_cos":0.7},"action":"none","trigger":"any"},
             {"name":"mano","type":"state","state":null,"active":false,"labels":["abierta","cerrada"],
              "dist":null,"count":0,"action":"none","trigger":"abierta"}]},
         "points":[[1.0,0.4]],"events":[],
         "events2":[{"kind":"start","t":12.5,"detector":"izquierda","action":null},
                    {"kind":"state","t":12.6,"state":"abierta","prev":"cerrada","detector":"mano","action":null}]}
    """.trimIndent()

    @Test
    fun parsesDataMessageWithDetectorsAndEvents() {
        val m = ServerJson.parseMessage(dataMessage)!!
        assertEquals(mapOf("izquierda" to 5, "abierta" to 3), m.examples)
        assertEquals("", m.recording)
        val p = m.phase2!!
        assertTrue(p.gyro)
        assertFalse(p.phoneMoving)
        assertEquals(2, p.detectors.size)
        assertEquals(DetectorType.EVENT, p.detectors[0].type)
        assertEquals("any", p.detectors[0].trigger)
        assertEquals(listOf("abierta", "cerrada"), p.detectors[1].labels)
        assertNull(p.detectors[1].state)
        assertEquals(2, m.events.size)
        assertEquals(ServerEvent("izquierda", "start", 12.5), m.events[0])
        assertEquals("abierta", m.events[1].state)
    }

    @Test
    fun ignoresOtherMessageTypesAndGarbage() {
        assertNull(ServerJson.parseMessage("""{"type":"info","text":"hola"}"""))
        assertNull(ServerJson.parseMessage("""{"type":"app_event","event":{}}"""))
        assertNull(ServerJson.parseMessage("no es json"))
    }

    @Test
    fun trainResultQuality() {
        val good = ServerJson.parseTrain("""{"ok":true,"detector":"izquierda","info":{"consistency":0.91,"u":[1,0,0]}}""")
        assertTrue(good.ok && good.good)
        assertEquals(0.91, good.consistency!!, 1e-9)
        val weak = ServerJson.parseTrain("""{"ok":true,"detector":"mano","info":{"separation":1.4,"labels":["a","b"]}}""")
        assertTrue(weak.ok)
        assertFalse(weak.good)
        val error = ServerJson.parseTrain("""{"ok":false,"error":"no hay ejemplos de 'x'"}""")
        assertFalse(error.ok)
        assertEquals("no hay ejemplos de 'x'", error.error)
    }

    @Test
    fun parsesAgentReplyAndSteps() {
        val reply = ServerJson.parseAgent(
            """{"reply":"Listo, enseñemos 'izquierda'.","steps":[
                {"type":"record","label":"izquierda","count":5,"detector_type":"event"},
                {"type":"train","detector_type":"event","name":"izquierda","label":"izquierda","trigger":"short"},
                {"type":"bind","detector":"izquierda","device":"luz"},
                {"type":"volar"}]}""",
        )!!
        assertEquals("Listo, enseñemos 'izquierda'.", reply.reply)
        assertEquals(AgentStep.Record("izquierda", 5, DetectorType.EVENT), reply.steps[0])
        assertEquals(
            AgentStep.Train(TrainRequest(DetectorType.EVENT, "izquierda", label = "izquierda", trigger = "short")),
            reply.steps[1],
        )
        assertEquals(AgentStep.Bind("izquierda", "luz"), reply.steps[2])
        assertEquals(AgentStep.Unknown("volar"), reply.steps[3])
    }

    @Test
    fun agentBodyCarriesContext() {
        val body = ServerJson.agentBody(
            "cuando mueva el dedo a la izquierda, prende la luz",
            devices = listOf("luz" to "Luz"),
            detectors = emptyList(),
            examples = mapOf("izquierda" to 2),
            bindings = emptyMap(),
        )
        val o = org.json.JSONObject(body)
        assertEquals("cuando mueva el dedo a la izquierda, prende la luz", o.getString("text"))
        val context = o.getJSONObject("context")
        val device = context.getJSONArray("devices").getJSONObject(0)
        assertEquals("luz", device.getString("id"))
        assertEquals("Luz", device.getString("name"))
        assertEquals(2, context.getJSONObject("examples").getInt("izquierda"))
    }

    @Test
    fun trainBodyAlwaysAsksServerNotToAct() {
        val body = ServerJson.trainBody(TrainRequest(DetectorType.EVENT, "izquierda", label = "izquierda", trigger = "double"))
        assertTrue(body.contains("\"action\":\"none\""))
        assertTrue(body.contains("\"type\":\"event\""))
        assertTrue(body.contains("\"trigger\":\"double\""))
    }
}
