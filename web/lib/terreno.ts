"use client";
// Cliente del servidor de terreno (terreno/servidor.py, FastAPI). Next reenvía /api, /fotos y /videos a ese
// servidor (next.config.mjs), que es quien cruza los datos por comuna: contornos, vecinas, el área elegida,
// el corredor con y sin capturas en terreno, y la serie histórica.
import { useCallback, useEffect, useRef, useState } from "react";

export type Parametros = {
  comunas: string[]; distritos: string[]; zona: number; km: number; w_calor: number; w_arbol: number; w_personas: number; perfil?: string;
};
export type InfoComunas = {
  comunas: string[]; vecinas: Record<string, string[]>; geo: Record<string, number[][][][]>;
  distritos: Record<string, string[]>; seleccion: string[]; parametros: Parametros;
};
export type HexCols = {
  h: string[]; comuna: string[]; distrito: string[]; u: (number | null)[]; lst: (number | null)[]; vivo: (number | null)[];
  ndvi: (number | null)[]; copa: (number | null)[]; pob: number[]; social: (number | null)[];
  parque: boolean[]; antes: boolean[]; ahora: boolean[]; checkpoint?: boolean[]; verificado: boolean[];
};
export type ResumenCorredor = {
  hexes: number; km: number; urgencia_cubierta: number; urgencia_azar: number; personas_cubiertas: number;
  personas_azar: number; verificados: number; checkpoints?: number; parques_conectados?: number; resistencia_media?: number | null;
};
export type Captura = {
  id: string; lat: number; lon: number; validacion: string; cuenta: boolean; fuente?: string; arbol_pct?: number;
  espacio_plantable?: string; obstaculos?: string[]; descripcion?: string; motivo_rechazo?: string;
  tomado_en?: string; medido_en?: string; precision_m?: number; video_id?: string; t_video_s?: number;
};
export type Recorrido = { id: string; inicio?: string; duracion_s?: number; archivo?: string; linea: [number, number][] };
export type Estado = {
  version: number; sel_id: number; seleccion: string[]; parametros: Parametros; hex: HexCols;
  capturas: Captura[]; recorridos: Recorrido[]; en_vivo: boolean; antes: ResumenCorredor; ahora: ResumenCorredor;
};
export type Cambio = Partial<{ comunas: string[]; distritos: string[]; zona: string[] | null; km: number; w_calor: number; w_arbol: number; w_personas: number; perfil: string }>;

const SONDEO_MS = 3000;

export function useTerreno() {
  const [info, setInfo] = useState<InfoComunas | null>(null);
  const [estado, setEstado] = useState<Estado | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const visto = useRef({ version: -1, sel_id: -1 });

  // El servidor manda los polígonos solo si no le decimos el sel_id actual; los arma h3-js aquí.
  const sondear = useCallback(async (forzar = false) => {
    try {
      const v = await (await fetch("/api/version")).json();
      if (!forzar && v.version === visto.current.version && v.sel_id === visto.current.sel_id) return;
      const d: Estado = await (await fetch(`/api/estado?sel_id=${v.sel_id}`)).json();
      visto.current = { version: d.version, sel_id: d.sel_id };
      setEstado(d);
      setError(null);
    } catch {
      setError("No hay conexión con el servidor de terreno.");
    }
  }, []);

  useEffect(() => {
    let vivo = true;
    fetch("/api/comunas").then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((i) => { if (vivo) { setInfo(i); sondear(true); } })
      .catch(() => vivo && setError("No hay conexión con el servidor de terreno."));
    const t = setInterval(() => sondear(), SONDEO_MS);
    return () => { vivo = false; clearInterval(t); };
  }, [sondear]);

  const cambiar = useCallback(async (cuerpo: Cambio) => {
    setOcupado(true);
    try {
      const r = await fetch("/api/seleccion", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || String(r.status));
      await sondear(true);
    } catch (e) {
      setError(`No se pudo cambiar: ${(e as Error).message}`);
    } finally {
      setOcupado(false);
    }
  }, [sondear]);

  return { info, estado, error, ocupado, cambiar };
}

export async function historico(desde: string, hasta: string) {
  const r = await fetch(`/api/historico?desde=${desde}&hasta=${hasta}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || String(r.status));
  return r.json() as Promise<{ meses: number; h: string[]; lst: (number | null)[]; ndvi: (number | null)[] }>;
}
