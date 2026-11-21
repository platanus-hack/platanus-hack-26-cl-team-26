// MagneSense Logger: lee magnetometro y giroscopio y los manda a server.py.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useKeepAwake } from 'expo-keep-awake';
import { Gyroscope, Magnetometer, MagnetometerUncalibrated } from 'expo-sensors';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import {
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import AgentScreen from './src/AgentScreen';
import { ChatMsg, useAgentFeed } from './src/agentFeed';
import ProbeOverlay from './src/ProbeOverlay';
import { baseUrl, Clock, makeId, normalizeUrl, postBatch, Sample, SensorName } from './src/stream';

// Android 12+ limita a 200 Hz por sensor; iOS suele entregar hasta ~100 Hz
// de magnetometro. La pantalla muestra la frecuencia real que se obtiene.
const RATES = [50, 100, 200]; // Hz
const DEFAULT_RATE = 200;
const BATCH_MS = 40; // cada cuanto se envia un paquete (25 por segundo)
const UI_MS = 33; // refresco de pantalla (~30 por segundo)
const MAX_BUFFER = 6000; // si el servidor no responde, se descartan los mas viejos
const HISTORY = 120; // barras en el grafico (~4 s)
const STORAGE_KEY = 'magnesense-logger-settings-v2';

type Vec = { x: number; y: number; z: number };
const ZERO: Vec = { x: 0, y: 0, z: 0 };
const norm = (v: Vec) => Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);

// Minimo y maximo de la magnitud entre dos refrescos de pantalla: asi el
// grafico muestra los picos rapidos aunque haya ~7 lecturas por refresco.
type Span = { lo: number; hi: number };
class SpanTracker {
  lo = Infinity;
  hi = -Infinity;
  last: Span = { lo: 0, hi: 0 };
  add(v: number) {
    if (v < this.lo) this.lo = v;
    if (v > this.hi) this.hi = v;
  }
  take(): Span {
    if (this.lo !== Infinity) this.last = { lo: this.lo, hi: this.hi };
    else this.last = { lo: this.last.hi, hi: this.last.hi }; // sin lecturas nuevas
    this.lo = Infinity;
    this.hi = -Infinity;
    return this.last;
  }
}

type Stats = {
  sent: number;
  failed: number;
  samples: number;
  dropped: number;
  lastMs: number;
  lastError: string;
  magHz: number;
  gyroHz: number;
};
const EMPTY_STATS: Stats = {
  sent: 0, failed: 0, samples: 0, dropped: 0, lastMs: 0, lastError: '', magHz: 0, gyroHz: 0,
};

export default function App() {
  return (
    <SafeAreaProvider>
      <Main />
    </SafeAreaProvider>
  );
}

// Dos pestañas. Ambas quedan montadas (solo se oculta la otra) para que la
// transmision de sensores siga corriendo mientras se conversa con el agente.
function Main() {
  const [tab, setTab] = useState<'sensores' | 'agente'>('sensores');
  const [dataUrl, setDataUrl] = useState('');
  const feed = useAgentFeed(dataUrl);
  const nextLocal = useRef(1_000_000);
  const addLocal = (role: ChatMsg['role'], text: string) =>
    feed.setMessages((m) => m.concat({ id: nextLocal.current++, role, text }));

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <View style={styles.tabs}>
        {(['sensores', 'agente'] as const).map((t) => (
          <Pressable key={t} onPress={() => setTab(t)} style={[styles.tab, tab === t && styles.tabOn]}>
            <Text style={[styles.tabText, tab === t && styles.tabTextOn]}>
              {t === 'sensores' ? 'Sensores' : 'Agente'}
            </Text>
          </Pressable>
        ))}
      </View>
      <View style={[styles.page, tab !== 'sensores' && styles.hidden]}>
        <Logger onServer={setDataUrl} />
      </View>
      <View style={[styles.page, tab !== 'agente' && styles.hidden]}>
        <AgentScreen
          dataUrl={dataUrl}
          connected={feed.connected}
          messages={feed.messages}
          rules={feed.rules}
          actions={feed.actions}
          addLocal={addLocal}
        />
      </View>
      <ProbeOverlay probe={feed.probe} />
    </SafeAreaView>
  );
}

function Logger({ onServer }: { onServer: (dataUrl: string) => void }) {
  const [url, setUrl] = useState('');
  const [rate, setRate] = useState(DEFAULT_RATE);
  const [useMag, setUseMag] = useState(true);
  const [useGyro, setUseGyro] = useState(true);
  const [uncal, setUncal] = useState(true);
  const [running, setRunning] = useState(false);
  const [avail, setAvail] = useState({ mag: false, magUncal: false, gyro: false });
  const [testMsg, setTestMsg] = useState('');

  // Lo que se muestra en pantalla (se refresca 10 veces por segundo).
  const [mag, setMag] = useState<Vec>(ZERO);
  const [gyro, setGyro] = useState<Vec>(ZERO);
  const [magHist, setMagHist] = useState<Span[]>([]);
  const [gyroHist, setGyroHist] = useState<Span[]>([]);
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);

  // Estado mutable del envio (no provoca renders).
  const buffer = useRef<Sample[]>([]);
  const lastMag = useRef<Vec>(ZERO);
  const lastGyro = useRef<Vec>(ZERO);
  const counts = useRef({ mag: 0, gyro: 0 });
  const magSpan = useRef(new SpanTracker());
  const gyroSpan = useRef(new SpanTracker());
  const st = useRef<Stats>({ ...EMPTY_STATS });
  const inflight = useRef(false);
  const messageId = useRef(0);
  const session = useRef({ sessionId: makeId(), deviceId: makeId() });
  const clock = useRef(new Clock());

  // Disponibilidad de sensores y ajustes guardados.
  useEffect(() => {
    (async () => {
      const [mag, magUncal, gyro] = await Promise.all([
        Magnetometer.isAvailableAsync().catch(() => false),
        MagnetometerUncalibrated.isAvailableAsync().catch(() => false),
        Gyroscope.isAvailableAsync().catch(() => false),
      ]);
      setAvail({ mag, magUncal, gyro });
      if (!magUncal) setUncal(false);
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw) {
          const s = JSON.parse(raw);
          if (typeof s.url === 'string') setUrl(s.url);
          if (RATES.includes(s.rate)) setRate(s.rate);
          if (typeof s.useMag === 'boolean') setUseMag(s.useMag);
          if (typeof s.useGyro === 'boolean') setUseGyro(s.useGyro);
          if (typeof s.uncal === 'boolean') setUncal(s.uncal && magUncal);
        }
      } catch {
        // sin ajustes guardados: se usan los por defecto
      }
    })();
  }, []);

  useEffect(() => {
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ url, rate, useMag, useGyro, uncal })).catch(
      () => {}
    );
  }, [url, rate, useMag, useGyro, uncal]);

  // Suscripcion a los sensores: siempre activos para ver los valores en
  // pantalla; solo se guardan en el buffer cuando se esta transmitiendo.
  const runningRef = useRef(false);
  runningRef.current = running;
  useEffect(() => {
    const interval = Math.round(1000 / rate);
    const subs: { remove: () => void }[] = [];
    const push = (name: SensorName, d: Vec & { timestamp: number }) => {
      if (!runningRef.current) return;
      const b = buffer.current;
      b.push({ name, time: clock.current.toEpochNs(d.timestamp), values: { x: d.x, y: d.y, z: d.z } });
      if (b.length > MAX_BUFFER) {
        st.current.dropped += b.length - MAX_BUFFER;
        b.splice(0, b.length - MAX_BUFFER);
      }
    };

    if (useMag && (uncal ? avail.magUncal : avail.mag)) {
      const sensor = uncal ? MagnetometerUncalibrated : Magnetometer;
      const name: SensorName = uncal ? 'magnetometeruncalibrated' : 'magnetometer';
      sensor.setUpdateInterval(interval);
      subs.push(
        sensor.addListener((d) => {
          lastMag.current = d;
          counts.current.mag++;
          magSpan.current.add(norm(d));
          push(name, d);
        })
      );
    }
    if (useGyro && avail.gyro) {
      Gyroscope.setUpdateInterval(interval);
      subs.push(
        Gyroscope.addListener((d) => {
          lastGyro.current = d;
          counts.current.gyro++;
          gyroSpan.current.add((norm(d) * 180) / Math.PI);
          push('gyroscope', d);
        })
      );
    }
    return () => subs.forEach((s) => s.remove());
  }, [rate, useMag, useGyro, uncal, avail]);

  // Envio por paquetes.
  const dataUrl = normalizeUrl(url);
  useEffect(() => onServer(dataUrl), [dataUrl, onServer]);
  useEffect(() => {
    if (!running || !dataUrl) return;
    const timer = setInterval(async () => {
      if (inflight.current || buffer.current.length === 0) return;
      const batch = buffer.current;
      buffer.current = [];
      inflight.current = true;
      messageId.current += 1;
      const res = await postBatch(dataUrl, {
        messageId: messageId.current,
        sessionId: session.current.sessionId,
        deviceId: session.current.deviceId,
        payload: batch,
      });
      inflight.current = false;
      const s = st.current;
      s.lastMs = res.ms;
      if (res.ok) {
        s.sent += 1;
        s.samples += batch.length;
        s.lastError = '';
      } else {
        s.failed += 1;
        s.lastError = res.error ?? 'error';
        // Se reintentan en el proximo paquete (con tope MAX_BUFFER).
        buffer.current = batch.concat(buffer.current).slice(-MAX_BUFFER);
      }
    }, BATCH_MS);
    return () => clearInterval(timer);
  }, [running, dataUrl]);

  // Refresco de pantalla y medicion de frecuencia real.
  useEffect(() => {
    let lastT = Date.now();
    const timer = setInterval(() => {
      const m = lastMag.current;
      const g = lastGyro.current;
      setMag(m);
      setGyro(g);
      const ms = magSpan.current.take();
      const gs = gyroSpan.current.take();
      setMagHist((h) => h.concat(ms).slice(-HISTORY));
      setGyroHist((h) => h.concat(gs).slice(-HISTORY));
      const now = Date.now();
      if (now - lastT >= 1000) {
        const dt = (now - lastT) / 1000;
        st.current.magHz = counts.current.mag / dt;
        st.current.gyroHz = counts.current.gyro / dt;
        counts.current = { mag: 0, gyro: 0 };
        lastT = now;
      }
      setStats({ ...st.current });
    }, UI_MS);
    return () => clearInterval(timer);
  }, []);

  const toggle = () => {
    if (running) {
      setRunning(false);
      return;
    }
    buffer.current = [];
    clock.current.reset();
    messageId.current = 0;
    session.current.sessionId = makeId();
    st.current = { ...EMPTY_STATS };
    setRunning(true);
  };

  const testConnection = async () => {
    if (!dataUrl) {
      setTestMsg('Escribe primero la IP del notebook.');
      return;
    }
    setTestMsg('Probando...');
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    try {
      const res = await fetch(baseUrl(dataUrl) + '/status', { signal: ctrl.signal });
      setTestMsg(res.ok ? 'Conectado al servidor MagneSense.' : `El servidor respondio HTTP ${res.status}.`);
    } catch {
      setTestMsg('Sin respuesta. Revisa la IP y que el telefono este en la misma red WiFi.');
    } finally {
      clearTimeout(timer);
    }
  };

  const connected = running && stats.sent > 0 && !stats.lastError;
  const statusColor = !running ? '#8a8f98' : connected ? '#1f9d55' : stats.lastError ? '#d64545' : '#d69e2e';
  const statusText = !running
    ? 'Detenido'
    : connected
      ? `Transmitiendo · ${stats.lastMs} ms`
      : stats.lastError
        ? `Error: ${stats.lastError}`
        : 'Conectando...';

  return (
    <>
      {running && <KeepAwake />}
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>MagneSense Logger</Text>

        <View style={styles.card}>
          <Text style={styles.label}>Servidor (IP del notebook)</Text>
          <TextInput
            style={styles.input}
            value={url}
            onChangeText={setUrl}
            placeholder="192.168.1.20:8000"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType={Platform.OS === 'ios' ? 'url' : 'default'}
            editable={!running}
          />
          {!!dataUrl && <Text style={styles.hint}>Envia a {dataUrl}</Text>}
          <Pressable style={styles.secondaryBtn} onPress={testConnection}>
            <Text style={styles.secondaryBtnText}>Probar conexion</Text>
          </Pressable>
          {!!testMsg && <Text style={styles.hint}>{testMsg}</Text>}
        </View>

        <View style={styles.card}>
          <Row label="Magnetometro" value={useMag} onChange={setUseMag} disabled={running || !(avail.mag || avail.magUncal)} />
          <Row
            label="Sin calibrar (recomendado)"
            value={uncal}
            onChange={setUncal}
            disabled={running || !useMag || !avail.magUncal}
            sub
          />
          <Row label="Giroscopio" value={useGyro} onChange={setUseGyro} disabled={running || !avail.gyro} />
          <Text style={[styles.label, { marginTop: 10 }]}>Frecuencia</Text>
          <View style={styles.rates}>
            {RATES.map((r) => (
              <Pressable
                key={r}
                disabled={running}
                onPress={() => setRate(r)}
                style={[styles.rate, rate === r && styles.rateOn, running && { opacity: 0.5 }]}
              >
                <Text style={[styles.rateText, rate === r && styles.rateTextOn]}>{r} Hz</Text>
              </Pressable>
            ))}
          </View>
        </View>

        <Pressable
          style={[styles.mainBtn, { backgroundColor: running ? '#d64545' : '#2b6cb0' }, !dataUrl && { opacity: 0.5 }]}
          onPress={toggle}
          disabled={!dataUrl && !running}
        >
          <Text style={styles.mainBtnText}>{running ? 'Detener' : 'Transmitir'}</Text>
        </Pressable>
        <View style={styles.statusRow}>
          <View style={[styles.dot, { backgroundColor: statusColor }]} />
          <Text style={styles.statusText} numberOfLines={2}>{statusText}</Text>
        </View>

        <SensorCard
          title={uncal ? 'Magnetometro sin calibrar' : 'Magnetometro'}
          unit="µT"
          v={mag}
          magnitude={norm(mag)}
          hz={stats.magHz}
          hist={magHist}
          color="#2b6cb0"
          enabled={useMag}
          available={avail.mag || avail.magUncal}
        />
        <SensorCard
          title="Giroscopio"
          unit="rad/s"
          v={gyro}
          magnitude={(norm(gyro) * 180) / Math.PI}
          magnitudeUnit="°/s"
          hz={stats.gyroHz}
          hist={gyroHist}
          color="#b7791f"
          enabled={useGyro}
          available={avail.gyro}
        />

        <View style={styles.card}>
          <Text style={styles.label}>Envio</Text>
          <Text style={styles.mono}>
            paquetes ok {stats.sent} · fallidos {stats.failed}{'\n'}
            lecturas enviadas {stats.samples}
            {stats.dropped > 0 ? ` · descartadas ${stats.dropped}` : ''}
          </Text>
        </View>
      </ScrollView>
    </>
  );
}

function KeepAwake() {
  useKeepAwake();
  return null;
}

function Row(props: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  sub?: boolean;
}) {
  return (
    <View style={[styles.row, props.sub && { paddingLeft: 16 }]}>
      <Text style={[styles.rowText, props.disabled && { color: '#a0a4ab' }]}>{props.label}</Text>
      <Switch value={props.value} onValueChange={props.onChange} disabled={props.disabled} />
    </View>
  );
}

function SensorCard(props: {
  title: string;
  unit: string;
  v: Vec;
  magnitude: number;
  magnitudeUnit?: string;
  hz: number;
  hist: Span[];
  color: string;
  enabled: boolean;
  available: boolean;
}) {
  if (!props.available) {
    return (
      <View style={styles.card}>
        <Text style={styles.label}>{props.title}</Text>
        <Text style={styles.hint}>Este telefono no tiene este sensor.</Text>
      </View>
    );
  }
  if (!props.enabled) return null;
  const f = (n: number) => (n >= 0 ? ' ' : '') + n.toFixed(props.unit === 'µT' ? 2 : 3);
  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <Text style={styles.label}>{props.title}</Text>
        <Text style={styles.hint}>{props.hz.toFixed(0)} Hz</Text>
      </View>
      <Text style={styles.mono}>
        x {f(props.v.x)}   y {f(props.v.y)}   z {f(props.v.z)}  {props.unit}
      </Text>
      <Text style={[styles.big, { color: props.color }]}>
        {props.magnitude.toFixed(1)} <Text style={styles.bigUnit}>{props.magnitudeUnit ?? props.unit}</Text>
      </Text>
      <Spark data={props.hist} color={props.color} />
    </View>
  );
}

// Grafico con Views (sin librerias extra). Cada barra va del minimo al
// maximo de ese refresco, asi se ven los movimientos mas cortos.
function Spark({ data, color }: { data: Span[]; color: string }) {
  const H = 60;
  if (data.length < 2) return <View style={{ height: H }} />;
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of data) {
    if (s.lo < lo) lo = s.lo;
    if (s.hi > hi) hi = s.hi;
  }
  if (hi - lo < 1) {
    const mid = (hi + lo) / 2;
    lo = mid - 0.5;
    hi = mid + 0.5;
  }
  const y = (v: number) => ((v - lo) / (hi - lo)) * (H - 2);
  return (
    <View style={[styles.spark, { height: H }]}>
      {data.map((s, i) => (
        <View
          key={i}
          style={{
            flex: 1,
            marginBottom: y(s.lo),
            height: Math.max(2, y(s.hi) - y(s.lo)),
            backgroundColor: color,
            opacity: 0.8,
          }}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#f2f4f7' },
  tabs: { flexDirection: 'row', gap: 8, paddingHorizontal: 16, paddingTop: 8 },
  tab: { flex: 1, paddingVertical: 10, borderRadius: 10, backgroundColor: '#e2e8f0', alignItems: 'center' },
  tabOn: { backgroundColor: '#2b6cb0' },
  tabText: { fontWeight: '700', color: '#2d3748' },
  tabTextOn: { color: '#fff' },
  page: { flex: 1 },
  hidden: { display: 'none' },
  container: { padding: 16, paddingBottom: 40, gap: 12 },
  title: { fontSize: 24, fontWeight: '700', color: '#1a202c', marginTop: 4 },
  card: { backgroundColor: '#fff', borderRadius: 12, padding: 14, gap: 6 },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  label: { fontSize: 13, fontWeight: '600', color: '#4a5568', textTransform: 'uppercase', letterSpacing: 0.5 },
  hint: { fontSize: 13, color: '#718096' },
  input: { borderWidth: 1, borderColor: '#cbd5e0', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, color: '#1a202c' },
  secondaryBtn: { alignSelf: 'flex-start', paddingVertical: 8, paddingHorizontal: 12, borderRadius: 8, backgroundColor: '#edf2f7' },
  secondaryBtnText: { color: '#2b6cb0', fontWeight: '600' },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 2 },
  rowText: { fontSize: 16, color: '#1a202c' },
  rates: { flexDirection: 'row', gap: 8 },
  rate: { flex: 1, paddingVertical: 8, borderRadius: 8, backgroundColor: '#edf2f7', alignItems: 'center' },
  rateOn: { backgroundColor: '#2b6cb0' },
  rateText: { color: '#2d3748', fontWeight: '600' },
  rateTextOn: { color: '#fff' },
  mainBtn: { borderRadius: 12, paddingVertical: 16, alignItems: 'center' },
  mainBtnText: { color: '#fff', fontSize: 18, fontWeight: '700' },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 4 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  statusText: { flex: 1, color: '#2d3748' },
  mono: { fontFamily: Platform.select({ ios: 'Menlo', default: 'monospace' }), fontSize: 13, color: '#2d3748' },
  big: { fontSize: 30, fontWeight: '700' },
  bigUnit: { fontSize: 16, fontWeight: '600' },
  spark: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 4 },
});
