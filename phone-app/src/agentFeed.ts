// Conexion en vivo con el agente de server.py (rama feat/agente).
// Usa el mismo WebSocket que el panel web (/ws): ahi llegan el chat, las
// reglas y las instrucciones de grabacion/prueba ("probe").
import { useEffect, useRef, useState } from 'react';

import { baseUrl } from './stream';

export type ChatMsg = { id: number; role: 'user' | 'assistant' | 'tool'; text: string };
export type Rule = { id: number; detector: string; gesto: string; accion: string };
export type Action = {
  tipo: string;
  descripcion?: string;
  aprobada?: boolean;
  integrada?: boolean;
  url?: string;
  metodo?: string;
  argv?: string[];
};
export type Probe = { text: string; seconds: number; phase: 'prep' | 'rec' | 'probe'; at: number };

const TOOL_NAMES: Record<string, string> = {
  ver_estado: 'revisando el estado',
  grabar_ejemplos: 'grabando ejemplos',
  crear_detector: 'creando detector',
  probar_detector: 'probando detector',
  listar_acciones: 'revisando acciones',
  crear_accion: 'creando accion',
  conectar: 'conectando gesto y accion',
  desconectar: 'borrando regla',
  ejecutar_accion: 'probando accion',
  quitar_detector: 'quitando detector',
};

export function wsUrl(dataUrl: string): string {
  return baseUrl(dataUrl).replace(/^http/i, 'ws') + '/ws';
}

export function useAgentFeed(dataUrl: string) {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [actions, setActions] = useState<Record<string, Action>>({});
  const [probe, setProbe] = useState<Probe | null>(null);
  const [info, setInfo] = useState('');
  const nextId = useRef(1);

  useEffect(() => {
    if (!dataUrl) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const add = (role: ChatMsg['role'], text: string) =>
      setMessages((m) => m.concat({ id: nextId.current++, role, text }).slice(-200));

    const open = () => {
      ws = new WebSocket(wsUrl(dataUrl));
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(open, 2000);
      };
      ws.onerror = () => {}; // onclose reintenta
      ws.onmessage = (e) => {
        let m: any;
        try {
          m = JSON.parse(String(e.data));
        } catch {
          return;
        }
        if (m.type === 'agent') {
          if (m.role === 'tool') {
            const i = m.input || {};
            const what = i.nombre || i.etiqueta || i.accion || i.detector;
            add('tool', '· ' + (TOOL_NAMES[m.name] || m.name) + (what ? ` (${what})` : ''));
          } else if (m.text) {
            add(m.role, m.text);
          }
        } else if (m.type === 'rules') {
          setRules(m.reglas || []);
          setActions(m.acciones || {});
        } else if (m.type === 'probe') {
          setProbe(m.seconds ? { text: m.text, seconds: m.seconds, phase: m.phase || 'probe', at: Date.now() } : null);
        } else if (m.type === 'info' && m.text) {
          setInfo(m.text);
        }
        // "state" y "data" (señal en vivo) no se usan aqui
      };
    };
    open();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
      setConnected(false);
    };
  }, [dataUrl]);

  return { connected, messages, rules, actions, probe, info, setMessages };
}

export async function getJson(url: string, timeoutMs = 4000): Promise<any> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// El agente puede tardar (graba intentos de varios segundos), por eso el
// tiempo maximo es largo.
export async function postJson(url: string, body: object, timeoutMs = 300000): Promise<any> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}
