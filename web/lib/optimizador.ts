// Port de optimizer.py (contrato v3, ver CONTRATO.md) para recalcular el corredor en el navegador.
// La parte determinista (urgencia, Dijkstra, tramos, red continua) sigue a Python paso a paso.
// El trazado al azar usa otro generador que random.Random(0), así que sus cifras varían un poco.
import { getHexagonEdgeLengthAvg, gridDisk, UNITS } from "h3-js";

export type Hex = {
  h: string; p: string; c: string; t: number; tu: number | null; v: number | null;
  a: number; n: number; s: number; k: boolean; u: number;
};
export type Barrio = { p: string; t: number | null; conf: string; medido: string | null };
export type Resultado = {
  hexes: string[]; length_km: number; urgencia_cubierta: number; urgencia_azar: number;
  personas_cubiertas: number; personas_azar: number; tramos: string[][];
};

const EPS = 0.05;
const MIN_PERSONAS_HEX = 50;
const N_AZAR = 200;
const SEMILLAS = 20;

function percentil(orden: number[], p: number) {
  const pos = (p / 100) * (orden.length - 1);
  const i = Math.floor(pos);
  return i + 1 < orden.length ? orden[i] + (orden[i + 1] - orden[i]) * (pos - i) : orden[i];
}

// Min-max robusto (percentiles 2 y 98) a 0..1, como _norm.
export function norm(x: (number | null)[]): (number | null)[] {
  const ok = x.filter((v): v is number => v != null && !Number.isNaN(v)).sort((a, b) => a - b);
  if (!ok.length) return x.map(() => null);
  const lo = percentil(ok, 2), hi = percentil(ok, 98);
  return x.map((v) => (v == null ? null : hi > lo ? Math.min(1, Math.max(0, (v - lo) / (hi - lo))) : 0));
}

export function indiceCalor(df: Hex[], vivo: Barrio[] = []) {
  let calor = norm(df.map((d) => d.t)) as number[];
  const ok = vivo.filter((b) => (b.conf === "alta" || b.conf === "media") && b.t != null);
  if (new Set(ok.map((b) => b.p)).size >= 2) {
    const por = new Map(ok.map((b) => [b.p, b.t as number]));
    const nv = norm(df.map((d) => por.get(d.p) ?? null));
    calor = calor.map((c, i) => (nv[i] == null ? c : 0.6 * c + 0.4 * (nv[i] as number)));
  }
  return calor;
}

export function urgencia(df: Hex[], wc = 0.4, wa = 0.4, wp = 0.2, vivo: Barrio[] = []) {
  if (Math.min(wc, wa, wp) < 0 || wc + wa + wp <= 0) throw new Error("Pesos deben ser >= 0 y no todos 0");
  const calor = indiceCalor(df, vivo);
  const copa = norm(df.map((d) => d.a)) as number[];
  const pob = norm(df.map((d) => d.n)) as number[];
  return df.map((d, i) => {
    const pers = 0.7 * pob[i] + 0.3 * Math.min(1, Math.max(0, d.s));
    return (wc * calor[i] + wa * (1 - copa[i]) + wp * pers) / (wc + wa + wp);
  });
}

// Montículo binario sobre (distancia, índice), mismo orden que heapq con tuplas.
class Monticulo {
  a: [number, number][] = [];
  menor(i: number, j: number) {
    const x = this.a[i], y = this.a[j];
    return x[0] < y[0] || (x[0] === y[0] && x[1] < y[1]);
  }
  push(e: [number, number]) {
    const a = this.a;
    a.push(e);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (!this.menor(i, p)) break;
      [a[i], a[p]] = [a[p], a[i]];
      i = p;
    }
  }
  pop() {
    const a = this.a, top = a[0], fin = a.pop()!;
    if (a.length) {
      a[0] = fin;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && this.menor(l, m)) m = l;
        if (r < a.length && this.menor(r, m)) m = r;
        if (m === i) break;
        [a[i], a[m]] = [a[m], a[i]];
        i = m;
      }
    }
    return top;
  }
}

function dijkstra(vec: number[][], costo: number[], parque: boolean[]) {
  const n = vec.length;
  const dist = new Array(n).fill(Infinity), etiq = new Array(n).fill(-1), prev = new Array(n).fill(-1);
  for (let s = 0; s < n; s++) {
    if (!parque[s] || etiq[s] >= 0) continue;
    etiq[s] = s;
    const pila = [s];
    while (pila.length) {
      const u = pila.pop()!;
      dist[u] = 0;
      for (const v of vec[u]) if (parque[v] && etiq[v] < 0) { etiq[v] = s; pila.push(v); }
    }
  }
  const heap = new Monticulo();
  for (let u = 0; u < n; u++) if (parque[u]) heap.push([0, u]);
  while (heap.a.length) {
    const [d, u] = heap.pop();
    if (d > dist[u]) continue;
    for (const v of vec[u]) {
      if (d + costo[v] < dist[v]) {
        dist[v] = d + costo[v]; etiq[v] = etiq[u]; prev[v] = u;
        heap.push([dist[v], v]);
      }
    }
  }
  return { dist, etiq, prev };
}

type Tramo = [number, number, number[], number];

function tramosEntreParques(vec: number[][], dist: number[], etiq: number[], prev: number[], parque: boolean[], U: number[]) {
  const mejor = new Map<string, [number, number, number, number, number]>();
  for (let u = 0; u < vec.length; u++) {
    for (const v of vec[u]) {
      if (v > u && etiq[u] >= 0 && etiq[v] >= 0 && etiq[u] !== etiq[v]) {
        const a = Math.min(etiq[u], etiq[v]), b = Math.max(etiq[u], etiq[v]), c = dist[u] + dist[v];
        const k = a + "," + b;
        if (c > 0 && c < (mejor.get(k)?.[0] ?? Infinity)) mejor.set(k, [c, u, v, a, b]);
      }
    }
  }
  const cadena = (x: number) => {
    const out: number[] = [];
    while (x >= 0 && !parque[x]) { out.push(x); x = prev[x]; }
    return out;
  };
  const tramos: Tramo[] = [];
  for (const [, u, v, a, b] of mejor.values()) {
    const cam = [...cadena(u).reverse(), ...cadena(v)];
    tramos.push([a, b, cam, cam.reduce((s, i) => s + U[i], 0) / cam.length]);
  }
  return tramos.sort((x, y) => -x[3] - -y[3] || x[2].length - y[2].length);
}

function redContinua(tramos: Tramo[], paso: number, budget: number) {
  const crecer = (k0: number): [number[], number] => {
    const elegidos: number[] = [], usado = new Set<number>(), parques = new Set<number>();
    let total = 0, cola = [k0];
    while (cola.length) {
      const k = cola.shift()!;
      const [a, b, cam, um] = tramos[k];
      const nuevos = cam.filter((i) => !usado.has(i));
      if (!nuevos.length || (usado.size + nuevos.length) * paso > budget + 1e-9) continue;
      elegidos.push(k);
      nuevos.forEach((i) => usado.add(i));
      parques.add(a); parques.add(b);
      total += um * nuevos.length;
      cola = tramos.flatMap((t, j) =>
        !elegidos.includes(j) && (parques.has(t[0]) || parques.has(t[1]) || t[2].some((i) => usado.has(i))) ? [j] : []);
    }
    return [elegidos, total];
  };
  const redes = Array.from({ length: Math.min(SEMILLAS, tramos.length) }, (_, k) => crecer(k));
  return redes.length ? redes.reduce((m, r) => (r[1] > m[1] ? r : m))[0] : [];
}

function mulberry32(semilla: number) {
  return () => {
    semilla = (semilla + 0x6d2b79f5) | 0;
    let t = Math.imul(semilla ^ (semilla >>> 15), 1 | semilla);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function solveCorridor(df: Hex[], budgetKm = 3, wc = 0.4, wa = 0.4, wp = 0.2, vivo: Barrio[] = []): Resultado {
  const Utodo = urgencia(df, wc, wa, wp, vivo);
  const filas = df.flatMap((d, i) => (d.k || d.n >= MIN_PERSONAS_HEX ? [i] : []));
  const hexs = filas.map((i) => df[i].h);
  const U = filas.map((i) => Utodo[i]), parque = filas.map((i) => df[i].k), pob = filas.map((i) => df[i].n);
  const idx = new Map(hexs.map((h, i) => [h, i]));
  const vec = hexs.map((h) => gridDisk(h, 1).filter((v) => v !== h && idx.has(v)).map((v) => idx.get(v)!));
  const { dist, etiq, prev } = dijkstra(vec, U.map((u, i) => (parque[i] ? 0 : 1 / (EPS + u))), parque);
  const tramos = tramosEntreParques(vec, dist, etiq, prev, parque, U);
  const paso = Math.sqrt(3) * getHexagonEdgeLengthAvg(9, UNITS.km);

  const red = redContinua(tramos, paso, budgetKm);
  const sel: number[] = [], largos: number[] = [], usado = new Set<number>();
  for (const k of red) {
    const nuevos = tramos[k][2].filter((i) => !usado.has(i));
    nuevos.forEach((i) => usado.add(i));
    sel.push(...nuevos);
    largos.push(nuevos.length);
  }

  const rng = mulberry32(0);
  const elige = <T,>(xs: T[]) => xs[Math.floor(rng() * xs.length)];
  const inicio = vec.flatMap((vs, i) => (!parque[i] && vs.some((v) => parque[v]) ? [i] : []));
  const uAz: number[] = [], pAz: number[] = [];
  for (let r = 0; r < (sel.length && inicio.length ? N_AZAR : 0); r++) {
    const vis = new Set<number>();
    for (const k of largos) {
      const cam = [elige(inicio)];
      while (cam.length < k) {
        const op = vec[cam[cam.length - 1]].filter((v) => !parque[v] && !vis.has(v) && !cam.includes(v));
        if (!op.length) break;
        cam.push(elige(op));
      }
      cam.forEach((i) => vis.add(i));
    }
    const vs = [...vis];
    uAz.push(vs.reduce((s, i) => s + U[i], 0) / vs.length);
    pAz.push(vs.reduce((s, i) => s + pob[i], 0));
  }
  const media = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0);

  return {
    hexes: sel.map((i) => hexs[i]),
    length_km: sel.length * paso,
    urgencia_cubierta: sel.length ? media(sel.map((i) => U[i])) : 0,
    urgencia_azar: media(uAz),
    personas_cubiertas: sel.reduce((s, i) => s + pob[i], 0),
    personas_azar: Math.trunc(media(pAz)),
    tramos: red.map((k) => tramos[k][2].map((i) => hexs[i])),
  };
}
