"""MagneSense, fase 1: servidor, detector y panel en un solo archivo.

Uso:
    pip install fastapi "uvicorn[standard]" httpx
    python server.py
    Panel:    http://localhost:8000
    Telefono: Sensor Logger -> HTTP Push -> http://IP-del-notebook:8000/data

Actuador real (opcional): definir ACTUATOR_ON_URL y ACTUATOR_OFF_URL
(por ejemplo un Shelly: http://IP-shelly/relay/0?turn=on). Sin ellas la
lampara es solo la del panel.
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import socket
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

DATA_DIR = Path(__file__).resolve().parent / "data"
PORT = int(os.environ.get("PORT", "8000"))
ACTUATOR_ON_URL = os.environ.get("ACTUATOR_ON_URL", "")
ACTUATOR_OFF_URL = os.environ.get("ACTUATOR_OFF_URL", "")


# ---------------------------------------------------------------------------
# Lectura del formato del telefono
# ---------------------------------------------------------------------------

def _to_seconds(t) -> float | None:
    """Convierte un timestamp en s, ms, us o ns a segundos."""
    try:
        t = float(t)
    except (TypeError, ValueError):
        return None
    if t > 1e17:
        return t / 1e9
    if t > 1e14:
        return t / 1e6
    if t > 1e11:
        return t / 1e3
    return t


def extract_samples(body) -> list[dict]:
    """Saca lecturas de magnetometro de lo que mande el telefono.

    Devuelve [{"t": segundos, "x": uT, "y": uT, "z": uT, "uncal": bool}].

    Formato esperado de Sensor Logger (HTTP Push):
      {"messageId": 1, "sessionId": "...", "deviceId": "...",
       "payload": [{"name": "magnetometer", "time": 1700000000000000000,
                    "values": {"x": .., "y": .., "z": ..}}, ...]}
    Tambien acepta "magnetometeruncalibrated" y una lista simple de
    {"t"/"time", "x", "y", "z"}. Si el telefono manda otra cosa, mirar
    data/first_message.json y ajustar esta funcion.
    """
    if isinstance(body, dict):
        items = body.get("payload", body.get("samples", body.get("data", [body])))
    elif isinstance(body, list):
        items = body
    else:
        return []

    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", it.get("sensor", "magnetometer"))).lower()
        if "magnet" not in name:
            continue
        vals = it.get("values", it)
        try:
            x, y, z = float(vals["x"]), float(vals["y"]), float(vals["z"])
        except (KeyError, TypeError, ValueError):
            continue
        t = _to_seconds(it.get("time", it.get("t", it.get("timestamp"))))
        out.append({"t": t, "x": x, "y": y, "z": z, "uncal": "uncal" in name})
    return out


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class Detector:
    """Umbral sobre |B - linea base| con duracion minima e histeresis."""

    def __init__(self):
        # Parametros (ver documento tecnico, seccion 6)
        self.k = 6.0                 # umbral = k * ruido
        self.floor = 1.0             # uT, piso del umbral
        self.min_on = 0.150          # s sobre el umbral para activar
        self.min_off = 0.100         # s bajo umbral/2 para soltar
        self.baseline_tau = 4.0      # s, seguimiento de deriva en reposo
        self.smooth_tau = 0.040      # s, suavizado
        self.stuck_after = 6.0       # s activo -> nuevo reposo
        self.calib_seconds = 2.0
        self.mode = "toggle"         # "toggle" o "hold"
        self.reset()

    def reset(self):
        self.baseline = None         # [x, y, z]
        self.noise = 0.0
        self.smooth = None
        self.last_t = None
        self.signal = 0.0
        self.active = False
        self.lamp = False
        self.above_since = None
        self.below_since = None
        self.active_since = None
        self.activations = 0
        self.seen_uncal = False
        self.start_calibration()

    def start_calibration(self):
        self.calibrating = True
        self.calib_buf: list[tuple[float, float, float, float]] = []
        self.active = False
        self.above_since = self.below_since = self.active_since = None

    @property
    def threshold(self) -> float:
        return max(self.k * self.noise, self.floor)

    def _finish_calibration(self):
        n = len(self.calib_buf)
        bx = sum(s[1] for s in self.calib_buf) / n
        by = sum(s[2] for s in self.calib_buf) / n
        bz = sum(s[3] for s in self.calib_buf) / n
        var = sum((s[1] - bx) ** 2 + (s[2] - by) ** 2 + (s[3] - bz) ** 2
                  for s in self.calib_buf) / n
        self.baseline = [bx, by, bz]
        self.noise = math.sqrt(var)
        self.calibrating = False
        self.calib_buf = []

    def process(self, t: float, x: float, y: float, z: float) -> list[str]:
        """Procesa una lectura. Devuelve eventos: "on", "off", "lamp_on", ..."""
        events: list[str] = []
        dt = 0.0 if self.last_t is None else min(max(t - self.last_t, 0.0), 0.5)
        if self.last_t is not None and t + 1.0 < self.last_t:
            dt = 0.0                 # el reloj retrocedio (nueva sesion)
        self.last_t = t

        # Suavizado exponencial del vector
        if self.smooth is None:
            self.smooth = [x, y, z]
        else:
            a = dt / (self.smooth_tau + dt) if dt > 0 else 1.0
            self.smooth = [s + a * (v - s) for s, v in zip(self.smooth, (x, y, z))]
        sx, sy, sz = self.smooth

        if self.calibrating:
            self.calib_buf.append((t, sx, sy, sz))
            if t - self.calib_buf[0][0] >= self.calib_seconds and len(self.calib_buf) >= 10:
                self._finish_calibration()
                events.append("calibrated")
            self.signal = 0.0
            return events

        bx, by, bz = self.baseline
        sig = math.sqrt((sx - bx) ** 2 + (sy - by) ** 2 + (sz - bz) ** 2)
        raw = math.sqrt((x - bx) ** 2 + (y - by) ** 2 + (z - bz) ** 2)
        self.signal = sig
        thr = self.threshold

        if not self.active:
            # La lectura cruda tambien debe seguir alta: asi la cola del
            # suavizado no alarga un pico breve hasta la duracion minima.
            if sig > thr and raw > thr / 2:
                if self.above_since is None:
                    self.above_since = t
                if t - self.above_since >= self.min_on:
                    self.active = True
                    self.active_since = t
                    self.below_since = None
                    self.activations += 1
                    events.append("on")
            else:
                self.above_since = None
                if sig < thr / 2 and dt > 0:
                    # Reposo: seguir deriva lenta y actualizar ruido
                    a = dt / self.baseline_tau
                    self.baseline = [b + a * (s - b) for b, s in zip(self.baseline, self.smooth)]
                    self.noise = math.sqrt(self.noise ** 2 + a * (sig ** 2 - self.noise ** 2))
        else:
            if sig < thr / 2:
                if self.below_since is None:
                    self.below_since = t
                if t - self.below_since >= self.min_off:
                    self.active = False
                    self.above_since = None
                    events.append("off")
            else:
                self.below_since = None
                if t - self.active_since >= self.stuck_after:
                    # El iman quedo en otra posicion: tomarla como reposo
                    self.baseline = list(self.smooth)
                    self.active = False
                    self.above_since = self.below_since = None
                    events.append("off")
                    events.append("rebaselined")

        # Lampara
        if "on" in events:
            if self.mode == "toggle":
                self.lamp = not self.lamp
            else:
                self.lamp = True
            events.append("lamp_on" if self.lamp else "lamp_off")
        if "off" in events and self.mode == "hold" and self.lamp:
            self.lamp = False
            events.append("lamp_off")
        return events

    def status(self) -> dict:
        return {
            "calibrating": self.calibrating,
            "baseline": self.baseline,
            "noise": round(self.noise, 4),
            "threshold": round(self.threshold, 4),
            "signal": round(self.signal, 4),
            "active": self.active,
            "lamp": self.lamp,
            "activations": self.activations,
            "config": {
                "k": self.k, "floor": self.floor, "min_on_ms": round(self.min_on * 1000),
                "min_off_ms": round(self.min_off * 1000), "mode": self.mode,
            },
        }


# ---------------------------------------------------------------------------
# Estado global, CSV, actuador y WebSocket
# ---------------------------------------------------------------------------

app = FastAPI(title="MagneSense")
det = Detector()
clients: set[WebSocket] = set()
recent_times: deque[float] = deque(maxlen=2000)   # para frecuencia de muestreo
state = {"csv_file": None, "csv_writer": None, "csv_path": None,
         "first_saved": False, "messages": 0, "samples": 0, "last_rx": None}


def _open_csv():
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"session_{datetime.now():%Y%m%d_%H%M%S}.csv"
    f = open(path, "w", newline="")
    w = csv.writer(f)
    w.writerow(["t", "x", "y", "z", "uncal", "signal", "threshold", "active", "lamp"])
    state.update(csv_file=f, csv_writer=w, csv_path=str(path))


def sample_rate() -> float:
    if len(recent_times) < 2:
        return 0.0
    span = recent_times[-1] - recent_times[0]
    return (len(recent_times) - 1) / span if span > 0 else 0.0


async def _call_actuator(on: bool):
    url = ACTUATOR_ON_URL if on else ACTUATOR_OFF_URL
    if not url:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as c:
            await c.get(url)
    except Exception as e:  # noqa: BLE001 - no botar el servidor por el enchufe
        print(f"[actuador] fallo {url}: {e}")


async def broadcast(msg: dict):
    dead = []
    text = json.dumps(msg)
    for ws in clients:
        try:
            await ws.send_text(text)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def _panel_state() -> dict:
    s = det.status()
    s.update(rate=round(sample_rate(), 1), messages=state["messages"],
             samples=state["samples"], csv=state["csv_path"],
             actuator=bool(ACTUATOR_ON_URL or ACTUATOR_OFF_URL))
    return s


@app.post("/data")
async def data(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "JSON invalido"}, status_code=400)

    if not state["first_saved"]:
        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "first_message.json").write_text(json.dumps(body, indent=2)[:200_000])
        state["first_saved"] = True
        print(f"[data] primer mensaje guardado en {DATA_DIR / 'first_message.json'}")

    samples = extract_samples(body)
    if any(s["uncal"] for s in samples):
        det.seen_uncal = True
    if det.seen_uncal:
        samples = [s for s in samples if s["uncal"]]
    now = time.time()
    for s in samples:
        if s["t"] is None:
            s["t"] = now
    samples.sort(key=lambda s: s["t"])

    if state["csv_writer"] is None:
        _open_csv()
    w = state["csv_writer"]
    points, events = [], []
    for s in samples:
        ev = det.process(s["t"], s["x"], s["y"], s["z"])
        events.extend(ev)
        recent_times.append(s["t"])
        points.append([round(s["t"], 4), round(det.signal, 3)])
        w.writerow([f"{s['t']:.4f}", s["x"], s["y"], s["z"], int(s["uncal"]),
                    f"{det.signal:.4f}", f"{det.threshold:.4f}", int(det.active), int(det.lamp)])
        for e in ev:
            if e in ("lamp_on", "lamp_off"):
                asyncio.create_task(_call_actuator(e == "lamp_on"))
    state["csv_file"].flush()
    state["messages"] += 1
    state["samples"] += len(samples)
    state["last_rx"] = now

    msg = _panel_state()
    msg.update(type="data", points=points, events=events)
    await broadcast(msg)
    return {"ok": True, "samples": len(samples)}


@app.post("/calibrate")
async def calibrate():
    det.start_calibration()
    await broadcast({"type": "info", "text": "Calibrando: no muevas el iman por 2 s"})
    return {"ok": True}


@app.post("/config")
async def config(request: Request):
    cfg = await request.json()
    if "k" in cfg:
        det.k = max(0.5, float(cfg["k"]))
    if "floor" in cfg:
        det.floor = max(0.0, float(cfg["floor"]))
    if "min_on_ms" in cfg:
        det.min_on = max(0.0, float(cfg["min_on_ms"]) / 1000)
    if "min_off_ms" in cfg:
        det.min_off = max(0.0, float(cfg["min_off_ms"]) / 1000)
    if cfg.get("mode") in ("toggle", "hold"):
        det.mode = cfg["mode"]
        if det.mode == "hold":
            det.lamp = det.active
    return det.status()


@app.post("/lamp")
async def lamp(request: Request):
    """Prende/apaga a mano (para probar el actuador)."""
    cfg = await request.json()
    det.lamp = bool(cfg.get("on"))
    asyncio.create_task(_call_actuator(det.lamp))
    await broadcast(dict(_panel_state(), type="state"))
    return {"ok": True, "lamp": det.lamp}


@app.get("/status")
async def status():
    return _panel_state()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps(dict(_panel_state(), type="state")))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


@app.get("/", response_class=HTMLResponse)
async def panel():
    return PANEL_HTML


PANEL_HTML = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MagneSense</title>
<style>
 body{font-family:system-ui,sans-serif;margin:0;background:#111;color:#eee}
 header{padding:12px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
 h1{font-size:20px;margin:0}
 #lamp{width:56px;height:56px;border-radius:50%;background:#333;border:2px solid #555;transition:.1s}
 #lamp.on{background:#ffd84a;box-shadow:0 0 40px #ffd84a}
 canvas{width:100%;height:320px;display:block;background:#1a1a1a}
 .stats{display:flex;gap:18px;flex-wrap:wrap;padding:8px 16px;font-variant-numeric:tabular-nums}
 .stats b{color:#9cf}
 .ctl{display:flex;gap:14px;flex-wrap:wrap;padding:8px 16px;align-items:center}
 button,select,input{font-size:14px}
 #msg{padding:4px 16px;color:#fc6;min-height:1.2em}
 .dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#c33}
 .dot.ok{background:#3c3}
</style></head><body>
<header><div id="lamp"></div><h1>MagneSense</h1>
 <span><span id="conn" class="dot"></span> <span id="connt">sin conexion</span></span></header>
<canvas id="c"></canvas>
<div class="stats">
 <span>Senal <b id="sig">-</b> µT</span><span>Umbral <b id="thr">-</b> µT</span>
 <span>Ruido <b id="noise">-</b> µT</span><span>Muestreo <b id="rate">-</b> Hz</span>
 <span>Activaciones <b id="acts">0</b></span><span>Estado <b id="st">-</b></span>
</div>
<div class="ctl">
 <button id="cal">Recalibrar (2 s quieto)</button>
 <label>Sensibilidad k <input id="k" type="range" min="1" max="20" step="0.5" value="6"> <span id="kv">6</span></label>
 <label>Duracion minima <input id="minon" type="number" min="0" max="2000" step="10" value="150" style="width:70px"> ms</label>
 <label>Modo <select id="mode"><option value="toggle">Alternar</option><option value="hold">Mientras dure</option></select></label>
 <button id="ltest">Probar lampara</button>
</div>
<div id="msg"></div>
<script>
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
let pts=[],thr=1,lastRx=0,lampOn=false;const WIN=10;
function $(i){return document.getElementById(i)}
function post(u,b){return fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})})}
$('cal').onclick=()=>post('/calibrate');
$('k').oninput=e=>{$('kv').textContent=e.target.value};
$('k').onchange=e=>post('/config',{k:+e.target.value});
$('minon').onchange=e=>post('/config',{min_on_ms:+e.target.value});
$('mode').onchange=e=>post('/config',{mode:e.target.value});
$('ltest').onclick=()=>post('/lamp',{on:!lampOn});
function apply(s){
 thr=s.threshold;lampOn=s.lamp;
 $('lamp').className=s.lamp?'on':'';
 $('sig').textContent=s.signal.toFixed(2);$('thr').textContent=s.threshold.toFixed(2);
 $('noise').textContent=s.noise.toFixed(3);$('rate').textContent=s.rate;
 $('acts').textContent=s.activations;
 $('st').textContent=s.calibrating?'calibrando':(s.active?'ACTIVO':'reposo');
 if(s.config){$('mode').value=s.config.mode;}
}
function connect(){
 const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
 ws.onopen=()=>{$('connt').textContent='panel conectado, esperando telefono'};
 ws.onclose=()=>{$('conn').className='dot';$('connt').textContent='sin conexion';setTimeout(connect,1000)};
 ws.onmessage=e=>{const m=JSON.parse(e.data);
  if(m.type==='info'){$('msg').textContent=m.text;return}
  apply(m);
  if(m.type==='data'){lastRx=Date.now();
   for(const p of m.points)pts.push([p[0],p[1],m.threshold]);
   if(m.events&&m.events.includes('calibrated'))$('msg').textContent='Calibrado. Ruido '+m.noise.toFixed(3)+' µT';
   if(m.events&&m.events.includes('rebaselined'))$('msg').textContent='Iman quieto en otra posicion: nueva linea base';
   if(pts.length){const tmax=pts[pts.length-1][0];pts=pts.filter(p=>p[0]>tmax-WIN)}
  }};
}
setInterval(()=>{const ok=Date.now()-lastRx<1500;$('conn').className='dot'+(ok?' ok':'');
 if(ok)$('connt').textContent='recibiendo del telefono';},500);
function draw(){
 const w=cv.width=cv.clientWidth*devicePixelRatio,h=cv.height=cv.clientHeight*devicePixelRatio;
 ctx.clearRect(0,0,w,h);
 if(pts.length>1){
  const tmax=pts[pts.length-1][0],tmin=tmax-WIN;
  let ymax=Math.max(thr*2,...pts.map(p=>p[1]))*1.1;
  const X=t=>(t-tmin)/WIN*w,Y=v=>h-v/ymax*h;
  ctx.strokeStyle='#f55';ctx.setLineDash([6,4]);ctx.beginPath();
  pts.forEach((p,i)=>{i?ctx.lineTo(X(p[0]),Y(p[2])):ctx.moveTo(X(p[0]),Y(p[2]))});ctx.stroke();
  ctx.setLineDash([]);ctx.strokeStyle='#6cf';ctx.lineWidth=2*devicePixelRatio;ctx.beginPath();
  pts.forEach((p,i)=>{i?ctx.lineTo(X(p[0]),Y(p[1])):ctx.moveTo(X(p[0]),Y(p[1]))});ctx.stroke();
  ctx.fillStyle='#888';ctx.font=(12*devicePixelRatio)+'px sans-serif';ctx.fillText(ymax.toFixed(1)+' µT',4,14*devicePixelRatio);
 }
 requestAnimationFrame(draw);
}
connect();draw();
</script></body></html>"""


def local_ips() -> list[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


if __name__ == "__main__":
    import uvicorn

    print("\n MagneSense listo")
    print(f"  Panel:    http://localhost:{PORT}")
    for ip in local_ips() or ["IP-del-notebook"]:
        print(f"  Telefono: http://{ip}:{PORT}/data")
    if ACTUATOR_ON_URL or ACTUATOR_OFF_URL:
        print(f"  Actuador: ON={ACTUATOR_ON_URL or '-'}  OFF={ACTUATOR_OFF_URL or '-'}")
    print()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
