// Aviso a pantalla completa cuando el agente graba un intento o prueba un
// detector: "Preparate" (azul) y luego "AHORA" (amarillo) con cuenta regresiva.
// No hay que tocar nada: tocar el telefono mueve el magnetometro.
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Probe } from './agentFeed';

export default function ProbeOverlay({ probe }: { probe: Probe | null }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!probe) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [probe]);
  if (!probe) return null;

  const left = Math.max(0, Math.ceil(probe.seconds - (now - probe.at) / 1000));
  const prep = probe.phase === 'prep';
  // El servidor manda "Preparate: <instruccion> · intento i de n" o "AHORA: ..."
  const match = /^(Preparate|AHORA): ([\s\S]*)$/.exec(probe.text);
  const head = match ? match[1] : '';
  const body = match ? match[2] : probe.text;
  const [instruction, attempt] = body.split('  ·  ');

  return (
    <View style={[styles.wrap, { backgroundColor: prep ? '#12324f' : '#4a3b00' }]} pointerEvents="none">
      {!!head && <Text style={[styles.head, { color: prep ? '#9cf' : '#ffd84a' }]}>{head}</Text>}
      <Text style={[styles.instruction, { color: prep ? '#e6f0ff' : '#fff3c4' }]}>{instruction}</Text>
      {!!attempt && <Text style={styles.attempt}>{attempt}</Text>}
      <Text style={[styles.count, { color: prep ? '#9cf' : '#ffd84a' }]}>{left}</Text>
      <Text style={styles.note}>
        {prep ? 'No toques el celular' : 'Haz el movimiento ahora'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { ...StyleSheet.absoluteFill, alignItems: 'center', justifyContent: 'center', padding: 24, zIndex: 10, elevation: 10 },
  head: { fontSize: 28, fontWeight: '800', letterSpacing: 1 },
  instruction: { fontSize: 34, fontWeight: '800', textAlign: 'center', marginTop: 12 },
  attempt: { fontSize: 18, color: '#cbd5e0', marginTop: 12 },
  count: { fontSize: 120, fontWeight: '800', marginTop: 16 },
  note: { fontSize: 16, color: '#cbd5e0', marginTop: 8 },
});
