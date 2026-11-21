// Envio de lecturas al servidor MagneSense (server.py, POST /data).
// Usa el mismo JSON que el "HTTP Push" de Sensor Logger, asi el servidor
// no necesita cambios:
//   {"messageId": 1, "sessionId": "...", "deviceId": "...",
//    "payload": [{"name": "magnetometeruncalibrated", "time": <ns epoch>,
//                 "values": {"x": .., "y": .., "z": ..}}, ...]}

export type SensorName = 'magnetometer' | 'magnetometeruncalibrated' | 'gyroscope';

export type Sample = {
  name: SensorName;
  time: number; // nanosegundos desde 1970 (como Sensor Logger)
  values: { x: number; y: number; z: number };
};

export type SendResult = { ok: boolean; error?: string; ms: number };

// Acepta "192.168.1.5", "192.168.1.5:8000" o una URL completa.
export function normalizeUrl(input: string): string {
  let url = input.trim();
  if (!url) return '';
  if (!/^https?:\/\//i.test(url)) url = 'http://' + url;
  const afterHost = url.replace(/^https?:\/\/[^/]+/i, '');
  if (afterHost === '' || afterHost === '/') {
    const host = url.replace(/\/$/, '');
    url = (/:\d+$/.test(host) ? host : host + ':8000') + '/data';
  }
  return url;
}

// URL base (sin /data), para el boton "Probar conexion" que llama a /status.
export function baseUrl(dataUrl: string): string {
  return dataUrl.replace(/\/data\/?$/, '');
}

// Los timestamps de expo-sensors vienen en segundos desde el arranque del
// telefono. Se fija un desfase al primer dato para pasarlos a hora real,
// compartido entre sensores para que queden en el mismo reloj.
export class Clock {
  private offset: number | null = null;

  reset() {
    this.offset = null;
  }

  toEpochNs(sensorSeconds: number): number {
    if (this.offset === null) {
      // Si ya parece hora real (posterior a 2001), no hay desfase.
      this.offset = sensorSeconds > 1e9 ? 0 : Date.now() / 1000 - sensorSeconds;
    }
    return Math.round((sensorSeconds + this.offset) * 1e9);
  }
}

export async function postBatch(
  url: string,
  body: object,
  timeoutMs = 3000
): Promise<SendResult> {
  const start = Date.now();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}`, ms: Date.now() - start };
    return { ok: true, ms: Date.now() - start };
  } catch (e) {
    const msg = ctrl.signal.aborted ? 'sin respuesta (timeout)' : String((e as Error)?.message ?? e);
    return { ok: false, error: msg, ms: Date.now() - start };
  } finally {
    clearTimeout(timer);
  }
}

export function makeId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}
