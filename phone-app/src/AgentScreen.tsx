// Pestaña "Agente": conversar con el agente de MagneSense desde el celular.
import { useEffect, useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import type { ScrollViewInstance } from 'react-native';

import { Action, ChatMsg, getJson, postJson, Rule } from './agentFeed';
import { baseUrl } from './stream';

type Props = {
  dataUrl: string;
  connected: boolean;
  messages: ChatMsg[];
  rules: Rule[];
  actions: Record<string, Action>;
  addLocal: (role: ChatMsg['role'], text: string) => void;
};

const EXAMPLE =
  'Ej: si muevo el iman de izquierda a derecha se apaga la luz, y de derecha a izquierda se prende';

export default function AgentScreen({ dataUrl, connected, messages, rules, actions, addLocal }: Props) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ available: boolean; reason?: string } | null>(null);
  const scroll = useRef<ScrollViewInstance>(null);
  const base = dataUrl ? baseUrl(dataUrl) : '';

  useEffect(() => {
    if (!base) return;
    getJson(base + '/agent/status')
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [base, connected]);

  const send = async () => {
    const t = text.trim();
    if (!t || busy || !base) return;
    setText('');
    setBusy(true);
    if (!connected) addLocal('user', t);
    try {
      const r = await postJson(base + '/agent', { text: t });
      // Con WebSocket la respuesta ya llego por ahi; sin el, mostrarla aqui
      if (!connected) addLocal('assistant', r.reply || r.error || 'Sin respuesta');
    } catch {
      addLocal('assistant', 'No pude hablar con el servidor. Revisa la IP en la pestaña Sensores.');
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!base) return;
    await postJson(base + '/agent/reset', {}, 4000).catch(() => {});
    addLocal('tool', '· conversacion nueva');
  };

  const approve = (name: string) => postJson(base + '/actions/approve', { name }, 4000).catch(() => {});

  if (!dataUrl) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyText}>
          Primero escribe la IP del notebook en la pestaña Sensores y empieza a transmitir.
        </Text>
      </View>
    );
  }

  const pending = Object.entries(actions).filter(([, a]) => !a.integrada && !a.aprobada);

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
    >
      <View style={styles.head}>
        <View style={[styles.dot, { backgroundColor: connected ? '#1f9d55' : '#d64545' }]} />
        <Text style={styles.headText} numberOfLines={2}>
          {!connected
            ? 'Sin conexion con el servidor'
            : status && !status.available
              ? `Agente no disponible: ${status.reason}`
              : 'Agente listo'}
        </Text>
        <Pressable onPress={reset} style={styles.smallBtn}>
          <Text style={styles.smallBtnText}>Nueva</Text>
        </Pressable>
      </View>

      <ScrollView
        ref={scroll}
        style={{ flex: 1 }}
        contentContainerStyle={styles.chat}
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })}
        keyboardShouldPersistTaps="handled"
      >
        {messages.length === 0 && (
          <Text style={styles.hint}>
            Cuentale al agente que movimiento quieres usar y que debe hacer. Te va a pedir grabar el
            movimiento 3 veces: deja el celular apoyado y quieto, y sigue las instrucciones en pantalla.
          </Text>
        )}
        {messages.map((m) => (
          <View key={m.id} style={[styles.msg, m.role === 'user' ? styles.user : m.role === 'tool' ? styles.tool : styles.assistant]}>
            <Text style={m.role === 'tool' ? styles.toolText : m.role === 'user' ? styles.userText : styles.msgText}>
              {m.text}
            </Text>
          </View>
        ))}
        {busy && <Text style={styles.hint}>El agente esta trabajando...</Text>}

        {rules.length > 0 && (
          <View style={styles.card}>
            <Text style={styles.label}>Reglas</Text>
            {rules.map((r) => (
              <Text key={r.id} style={styles.rule}>
                {r.detector} · {r.gesto} → <Text style={{ fontWeight: '700' }}>{r.accion}</Text>
                {actions[r.accion] && !actions[r.accion].aprobada ? '  (pendiente)' : ''}
              </Text>
            ))}
          </View>
        )}
        {pending.map(([name, a]) => (
          <View key={name} style={[styles.card, styles.pending]}>
            <Text style={styles.label}>Accion pendiente de aprobacion</Text>
            <Text style={styles.rule}>
              {name}: {a.tipo === 'http' ? `${a.metodo} ${a.url}` : (a.argv || []).join(' ')}
            </Text>
            <Pressable onPress={() => approve(name)} style={[styles.smallBtn, { alignSelf: 'flex-start' }]}>
              <Text style={styles.smallBtnText}>Aprobar</Text>
            </Pressable>
          </View>
        ))}
      </ScrollView>

      <View style={styles.ask}>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          placeholder={EXAMPLE}
          multiline
          editable={!busy}
        />
        <Pressable onPress={send} disabled={busy || !text.trim()} style={[styles.send, (busy || !text.trim()) && { opacity: 0.5 }]}>
          <Text style={styles.sendText}>{busy ? '...' : 'Enviar'}</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  emptyText: { fontSize: 16, color: '#4a5568', textAlign: 'center' },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 16, paddingVertical: 8 },
  headText: { flex: 1, color: '#2d3748' },
  dot: { width: 10, height: 10, borderRadius: 5 },
  chat: { padding: 16, gap: 8 },
  hint: { color: '#718096', fontSize: 14 },
  msg: { borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8, maxWidth: '85%' },
  user: { alignSelf: 'flex-end', backgroundColor: '#2b6cb0' },
  assistant: { alignSelf: 'flex-start', backgroundColor: '#fff' },
  tool: { alignSelf: 'flex-start', paddingVertical: 0 },
  msgText: { fontSize: 15, color: '#1a202c' },
  userText: { fontSize: 15, color: '#fff' },
  toolText: { fontSize: 12, color: '#718096' },
  card: { backgroundColor: '#fff', borderRadius: 12, padding: 12, gap: 4 },
  pending: { borderLeftWidth: 4, borderLeftColor: '#dd6b20' },
  label: { fontSize: 12, fontWeight: '600', color: '#4a5568', textTransform: 'uppercase' },
  rule: { fontSize: 14, color: '#2d3748' },
  ask: { flexDirection: 'row', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: '#e2e8f0', backgroundColor: '#f2f4f7' },
  input: { flex: 1, maxHeight: 110, borderWidth: 1, borderColor: '#cbd5e0', borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8, fontSize: 15, backgroundColor: '#fff', color: '#1a202c' },
  send: { backgroundColor: '#2b6cb0', borderRadius: 10, paddingHorizontal: 16, justifyContent: 'center' },
  sendText: { color: '#fff', fontWeight: '700' },
  smallBtn: { backgroundColor: '#edf2f7', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 6 },
  smallBtnText: { color: '#2b6cb0', fontWeight: '600' },
});
