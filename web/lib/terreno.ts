"use client";
// Cliente del servidor de terreno (terreno/servidor.py, FastAPI). Next reenvía /api, /fotos, /videos y /audios a ese
// servidor (next.config.mjs), que es quien cruza los datos por comuna: contornos, vecinas, el área elegida,
// el corredor con y sin capturas en terreno, y la serie histórica.
import { useCallback, useEffect, useRef, useState } from "react";

// Para quién se traza el corredor: una o más.
export type Especie = "humanos" | "aves" | "abejas";
export type Parametros = {
  comunas: string[]; distritos: string[]; zona: number; km: number; w_calor: number; w_arbol: number; w_personas: number;
  w_bio?: number; vecinas?: boolean; perfil?: string; especies?: Especie[]; birdnet?: string;
};
export type InfoComunas = {
  comunas: string[]; vecinas: Record<string, string[]>; geo: Record<string, number[][][][]>;
  distritos: Record<string, string[]>; seleccion: string[]; parametros: Parametros;
};
export type HexCols = {
  h: string[]; comuna: string[]; distrito: string[]; u: (number | null)[]; lst: (number | null)[]; vivo: (number | null)[];
  ndvi: (number | null)[]; copa: (number | null)[]; pob: number[]; social: (number | null)[];
  parque: boolean[]; antes: boolean[]; ahora: boolean[]; checkpoint?: boolean[]; verificado: boolean[];
  bio?: (number | null)[]; especies?: string[]; polinizadores?: number[];
  fotos?: number[]; escuchas?: number[];  // cuántas fotos que cuentan y escuchas analizadas hay en cada cuadra
};
export type ResumenCorredor = {
  hexes: number; km: number; urgencia_cubierta: number; urgencia_azar: number; personas_cubiertas: number;
  personas_azar: number; verificados: number; km_min?: number | null;
  checkpoints?: number; parques_conectados?: number; resistencia_media?: number | null;
};
export type Captura = {
  id: string; lat: number; lon: number; validacion: string; cuenta: boolean; fuente?: string; arbol_pct?: number;
  espacio_plantable?: string; obstaculos?: string[]; descripcion?: string; motivo_rechazo?: string;
  tomado_en?: string; medido_en?: string; precision_m?: number; video_id?: string; t_video_s?: number;
  tipo_foto?: string | null; fauna?: Avistamiento[]; flores?: string | null;
};
export type Avistamiento = { grupo: string; nombre: string; cantidad: number };
export type Deteccion = { cientifico: string; comun: string; confianza: number; inicio_s: number; fin_s: number };
export type Ruido = { db: number; max_db: number; nivel: "bajo" | "medio" | "alto" };
export type Escucha = {
  id: string; lat: number; lon: number; duracion_s: number; analizada: boolean; detecciones: Deteccion[];
  ruido?: Ruido | null; concluyente?: boolean; archivo?: string | null; video_id?: string; desde_s?: number;
  hasta_s?: number; tomado_en?: string | null; medido_en?: string; precision_m?: number | null;
};
export type Recorrido = { id: string; inicio?: string; duracion_s?: number; archivo?: string; linea: [number, number][] };
export type Estado = {
  version: number; sel_id: number; seleccion: string[]; parametros: Parametros; hex: HexCols; lst_fecha: string | null;
  recorridos: Recorrido[]; en_vivo: boolean; antes: ResumenCorredor; ahora: ResumenCorredor;
  totales: { capturas: number; cuentan: number; escuchas: number };
  fauna_corredor?: { especies: string[]; polinizadores: number };
  fuera?: { h: string; comuna: string | null; isla?: boolean }[];   // cuadras del corredor en comunas vecinas
};
export type DetalleHex = {
  h3_index: string; comuna: string | null; n_fotos: number; n_escuchas: number; fotos: Captura[]; escuchas: Escucha[];
  especies?: string[]; polinizadores?: number; flores?: number | null;
};
export type Cambio = Partial<{ comunas: string[]; distritos: string[]; zona: string[] | null; km: number; w_calor: number; w_arbol: number; w_personas: number; w_bio: number; vecinas: boolean; perfil: string; especies: Especie[] }>;

const SONDEO_MS = 3000;
// Sesión de este navegador en el servidor: área, presupuesto y pesos son solo suyos y se pierden al recargar.
const SESION = (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}${Math.random()}`).replace(/[^A-Za-z0-9]/g, "").slice(0, 32);

export function useTerreno() {
  const [info, setInfo] = useState<InfoComunas | null>(null);
  const [estado, setEstado] = useState<Estado | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const visto = useRef({ version: -1, sel_id: -1 });

  // El servidor manda los polígonos solo si no le decimos el sel_id actual; los arma h3-js aquí.
  const sondear = useCallback(async (forzar = false) => {
    try {
      const v = await (await fetch(`/api/version?s=${SESION}`)).json();
      if (!forzar && v.version === visto.current.version && v.sel_id === visto.current.sel_id) return;
      const d: Estado = await (await fetch(`/api/estado?sel_id=${v.sel_id}&s=${SESION}`)).json();
      visto.current = { version: d.version, sel_id: d.sel_id };
      setEstado(d);
      setError(null);
    } catch {
      setError("No hay conexión con el servidor de terreno.");
    }
  }, []);

  useEffect(() => {
    let vivo = true;
    fetch(`/api/comunas?s=${SESION}`).then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((i) => { if (vivo) { setInfo(i); sondear(true); } })
      .catch(() => vivo && setError("No hay conexión con el servidor de terreno."));
    const t = setInterval(() => sondear(), SONDEO_MS);
    return () => { vivo = false; clearInterval(t); };
  }, [sondear]);

  const cambiar = useCallback(async (cuerpo: Cambio) => {
    setOcupado(true);
    try {
      const r = await fetch(`/api/seleccion?s=${SESION}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
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

// Lo registrado en terreno en una cuadra (fotos que cuentan y escuchas de aves), lo más nuevo primero.
export async function detalleHex(h: string, n = 6) {
  const r = await fetch(`/api/hexagono/${h}?n=${n}`);
  if (!r.ok) throw new Error(String(r.status));
  return r.json() as Promise<DetalleHex>;
}

export async function historico(desde: string, hasta: string) {
  const r = await fetch(`/api/historico?desde=${desde}&hasta=${hasta}&s=${SESION}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || String(r.status));
  return r.json() as Promise<{ meses: number; h: string[]; lst: (number | null)[]; ndvi: (number | null)[] }>;
}
