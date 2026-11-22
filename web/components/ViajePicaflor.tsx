"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { formato, menosMovimiento } from "./movimiento";

// Cortometraje: el viaje del picaflor chico del Cerro Renca al Cerro San Cristóbal (viaje_picaflor.py → viaje.json).
// Acto 1: la ciudad de hoy en línea recta; cada cuadra es un edificio o un árbol según su copa medida.
// Acto 2: la ruta para aves con el corredor plantado (supuesto: es lo que propone Viridis).
type Cuadra = { h: string; copa: number; parque: boolean };
type Ruta = { cuadras: Cuadra[]; km: number; sin_arboles_max: number; copa_media: number };
type Viaje = { especie: string; registros_santiago: number; desde: number; sin_copa_pct: number; recta: Ruta; corredor: Ruta };

const W = 1200, H = 540;          // lienzo
const SEG = 130;                  // ancho de una cuadra en el lienzo
const CERRO = 460;                // ancho de cada cerro
const AVE_X = 380;                // el picaflor queda fijo en pantalla; la ciudad pasa
const MS_CUADRA = 620;
const T_INTRO = 4500, T_PAUSA = 3800, T_CAMBIO = 3200, T_FIN = 6500;

let viajeCache: Promise<Viaje | null> | null = null;

// Número estable (0..1) a partir del identificador de una cuadra, para alturas y ventanas de los edificios.
const azar = (s: string, k = 0) => { let h = 2166136261 ^ k; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return ((h >>> 0) % 1000) / 1000; };
const mezcla = (a: string, b: string, f: number) => {
  const p = (x: string) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
  const [r1, g1, b1] = p(a), [r2, g2, b2] = p(b);
  return `rgb(${Math.round(r1 + (r2 - r1) * f)},${Math.round(g1 + (g2 - g1) * f)},${Math.round(b1 + (b2 - b1) * f)})`;
};
const esArbol = (c: Cuadra, umbral: number) => c.parque || c.copa >= umbral;
const duracion = (v: Viaje) => T_INTRO + v.recta.cuadras.length * MS_CUADRA + T_PAUSA + T_CAMBIO + v.corredor.cuadras.length * MS_CUADRA + T_FIN;

function rachaHasta(r: Ruta, k: number, umbral: number) {
  let racha = 0;
  for (let i = 0; i <= Math.min(k, r.cuadras.length - 1); i++) racha = esArbol(r.cuadras[i], umbral) ? 0 : racha + 1;
  return racha;
}

type Escena = { acto: 0 | 1 | 2 | 3; ruta: Ruta; x: number; racha: number; calor: number; texto: string; sub?: string; contador?: string };

// Qué pasa en el instante t (ms): acto, dónde va el ave (en cuadras), cuánto calor y qué dice el texto.
function escena(v: Viaje, t: number): Escena {
  const n1 = v.recta.cuadras.length, n2 = v.corredor.cuadras.length;
  const d1 = n1 * MS_CUADRA, d2 = n2 * MS_CUADRA;
  const fin1 = T_INTRO + d1, cambio = fin1 + T_PAUSA, ini2 = cambio + T_CAMBIO, fin2 = ini2 + d2;
  if (t < T_INTRO) return { acto: 0, ruta: v.recta, x: 0, racha: 0, calor: 0, texto: "Esta es la historia de un picaflor chico.",
    sub: `Es el colibrí que más se ve en Santiago: ${formato(v.registros_santiago)} registros desde ${v.desde}. Vive en el Cerro Renca.` };
  if (t < fin1) {
    const f = (t - T_INTRO) / d1, k = Math.floor(f * n1);
    const racha = rachaHasta(v.recta, k, v.sin_copa_pct);
    const texto = racha >= 10 ? "No hay dónde posarse. No hay una sola flor." : racha >= 4 ? "Cemento, autos, calor." : "Quiere llegar al Cerro San Cristóbal. Tiene que cruzar la ciudad.";
    return { acto: 1, ruta: v.recta, x: f * n1, racha, calor: Math.min(1, racha / 12), texto,
      contador: `${racha} ${racha === 1 ? "cuadra seguida" : "cuadras seguidas"} sin un árbol` };
  }
  if (t < cambio) return { acto: 1, ruta: v.recta, x: n1, racha: v.recta.sin_arboles_max, calor: 1, texto: `Hoy cruza ${v.recta.sin_arboles_max} cuadras seguidas sin un árbol.`,
    sub: "Muchos no llegan. Los cerros de Santiago son islas, y el cemento las separa." };
  if (t < ini2) return { acto: 2, ruta: v.corredor, x: 0, racha: 0, calor: 0.15, texto: "Ahora, la misma ciudad con un corredor verde.",
    sub: "Árboles donde descansar y flores donde comer, de isla en isla." };
  if (t < fin2) {
    const f = (t - ini2) / d2;
    return { acto: 2, ruta: v.corredor, x: f * n2, racha: 0, calor: 0.1, contador: "0 cuadras seguidas sin un árbol",
      texto: f < 0.5 ? "Cada pocas cuadras, un árbol. Cada pocos árboles, una flor." : "Sin apuro. Con sombra todo el camino." };
  }
  return { acto: 3, ruta: v.corredor, x: n2, racha: 0, calor: 0, texto: "Del Cerro Renca al San Cristóbal, de isla en isla.",
    sub: "Viridis traza los corredores verdes que Santiago necesita: para las personas, las aves y las abejas." };
}

function Cerro({ x, nombre, lado }: { x: number; nombre: string; lado: "izq" | "der" }) {
  const d = lado === "izq"
    ? `M${x} ${H - 70} L${x} 250 Q${x + 120} 150 ${x + 230} 200 Q${x + 330} 240 ${x + CERRO} ${H - 70} Z`
    : `M${x} ${H - 70} Q${x + 110} 250 ${x + 200} 190 Q${x + 290} 120 ${x + 360} 210 L${x + CERRO} 260 L${x + CERRO} ${H - 70} Z`;
  return (
    <g>
      <path d={d} fill="#4F6E31" />
      {[0, 1, 2, 3, 4, 5].map((i) => <circle key={i} cx={x + 70 + i * 62} cy={(lado === "izq" ? 240 : 250) + (i % 2) * 28 - (i === 2 || i === 3 ? 40 : 0)} r={26} fill="#3C5A26" />)}
      <text x={x + CERRO / 2} y={H - 92} textAnchor="middle" fontSize="22" fontWeight="700" fill="#F6EFD2">{nombre}</text>
    </g>
  );
}

function Arbol({ x, s, flores }: { x: number; s: number; flores: boolean }) {
  return (
    <g transform={`translate(${x} ${H - 70}) scale(${s})`}>
      <rect x={-7} y={-110} width={14} height={110} fill="#6B4F2E" rx={4} />
      <circle cx={0} cy={-140} r={52} fill="#5E9A3C" />
      <circle cx={-34} cy={-112} r={34} fill="#4F8A32" />
      <circle cx={34} cy={-114} r={36} fill="#4F8A32" />
      {flores && [[-30, -150], [22, -168], [40, -126], [-12, -104], [8, -140]].map(([fx, fy], i) => (
        <g key={i}><circle cx={fx} cy={fy} r={7} fill="#E85D8A" /><circle cx={fx} cy={fy} r={2.6} fill="#F6D04D" /></g>
      ))}
    </g>
  );
}

function Edificio({ x, c }: { x: number; c: Cuadra }) {
  const alto = 150 + azar(c.h) * 190, ancho = SEG - 22;
  const filas = Math.floor((alto - 30) / 34);
  return (
    <g>
      <rect x={x - ancho / 2} y={H - 70 - alto} width={ancho} height={alto} fill={mezcla("#9A9488", "#B7B0A2", azar(c.h, 1))} />
      {Array.from({ length: filas }, (_, f) => [0, 1, 2].map((k) => (
        <rect key={`${f}-${k}`} x={x - ancho / 2 + 14 + k * 30} y={H - 70 - alto + 18 + f * 34} width={16} height={18} fill={azar(c.h, f * 3 + k + 2) > 0.55 ? "#E8D9A8" : "#7C766B"} />
      )))}
    </g>
  );
}

// El picaflor: cuerpo, cabeza, pico largo, garganta roja, cola y un ala que bate rápido (más lento si está cansado).
function Ave({ y, aleteo, cansancio }: { y: number; aleteo: number; cansancio: number }) {
  const ala = Math.sin(aleteo) * (1 - cansancio * 0.55);
  return (
    <g transform={`translate(${AVE_X} ${y}) rotate(${cansancio * 14}) scale(1.6)`}>
      <path d="M8 -6 L52 -10 L8 0 Z" fill="#22281A" />
      <ellipse cx={-10} cy={0} rx={22} ry={12} fill="#2E7D4F" />
      <circle cx={6} cy={-5} r={10} fill="#2E7D4F" />
      <circle cx={9} cy={-8} r={2.4} fill="#F6EFD2" />
      <path d="M-4 6 Q4 12 12 6" stroke="#C0392B" strokeWidth={4} fill="none" />
      <path d="M-28 2 L-52 16 L-44 2 L-52 -12 Z" fill="#1F5A3A" />
      <path d={`M-8 -6 Q-22 ${-6 - 34 * ala} -38 ${-4 - 30 * ala} Q-22 ${-2 - 10 * ala} -4 -2 Z`} fill="#4FA46C" opacity={0.95} />
    </g>
  );
}

export default function ViajePicaflor() {
  const [v, setV] = useState<Viaje | null>(null);
  const [t, setT] = useState(0);
  const [andando, setAndando] = useState(false);
  const raf = useRef(0);
  const t0 = useRef(0);
  const caja = useRef<HTMLDivElement>(null);
  const visto = useRef(false);

  useEffect(() => {
    viajeCache ??= fetch("/data/viaje.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    let vivo = true;
    viajeCache.then((d) => vivo && setV(d));
    return () => { vivo = false; cancelAnimationFrame(raf.current); };
  }, []);

  const total = useMemo(() => (v ? duracion(v) : 0), [v]);

  function reproducir(desde = 0) {
    if (!v) return;
    cancelAnimationFrame(raf.current);
    if (menosMovimiento()) { setT(total); return; }
    t0.current = performance.now() - desde;
    setAndando(true);
    const tic = (ahora: number) => {
      const x = ahora - t0.current;
      setT(Math.min(x, total));
      if (x < total) raf.current = requestAnimationFrame(tic);
      else setAndando(false);
    };
    raf.current = requestAnimationFrame(tic);
  }
  const pausar = () => { cancelAnimationFrame(raf.current); setAndando(false); };

  // Empieza solo la primera vez que el corto se ve.
  useEffect(() => {
    if (!v || !caja.current) return;
    const ob = new IntersectionObserver(([en]) => { if (en.isIntersecting && !visto.current) { visto.current = true; reproducir(); } }, { threshold: 0.5 });
    ob.observe(caja.current);
    return () => ob.disconnect();
  }, [v]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!v) return <div ref={caja}><div className="b-cab"><h2>El viaje <em>del picaflor</em></h2></div><div className="sk" style={{ aspectRatio: `${W} / ${H}`, borderRadius: 24 }} /></div>;
  const e = escena(v, t);
  const n = e.ruta.cuadras.length;
  const largo = CERRO + n * SEG + CERRO;
  // Cámara: el ave va del centro del Renca al centro del San Cristóbal; la ciudad pasa por debajo.
  const aveMundo = CERRO * 0.55 + (e.acto === 3 ? n + 0.3 : e.x) * SEG;
  const cam = Math.max(0, Math.min(largo - W, aveMundo - AVE_X));
  const cansancio = e.acto === 1 ? Math.min(1, e.racha / 14) : 0;
  const posada = e.acto === 2 && Math.abs(((e.x * SEG) % (SEG * 2)) - SEG) < 14;   // se detiene un momento en las flores
  const y = (e.acto === 0 || e.acto === 3 ? 210 + Math.sin(t / 380) * 10 : 200 + cansancio * 130 + Math.sin(t / 260) * 6) + (posada ? 30 : 0);
  const cielo = mezcla("#BFDCE6", "#F2B36D", e.calor);
  const suelo = e.acto === 1 ? "#8E877A" : "#A8B38A";
  const crece = (i: number) => (e.acto === 2 ? Math.max(0, Math.min(1, (e.x - i + 3.2) / 1.6)) : 1);
  const subY = e.sub ? 40 : 0;

  return (
    <div ref={caja} className="corto">
      <div className="b-cab escalon"><h2>El viaje <em>del picaflor</em></h2></div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${e.texto} ${e.sub ?? ""} ${e.contador ?? ""}`}>
        <rect width={W} height={H} fill={cielo} />
        <circle cx={W - 150} cy={110} r={54 + e.calor * 26} fill={mezcla("#F6E7A8", "#F08A3C", e.calor)} opacity={0.9} />
        <path d={`M0 ${H - 150} L140 ${H - 250} L300 ${H - 190} L470 ${H - 300} L650 ${H - 210} L820 ${H - 320} L1010 ${H - 220} L1200 ${H - 280} L1200 ${H} L0 ${H} Z`}
          fill={mezcla("#9FB5C2", "#C8A27F", e.calor)} opacity={0.55} />
        <g transform={`translate(${-cam} 0)`}>
          <rect x={0} y={H - 70} width={largo} height={70} fill={suelo} />
          <Cerro x={0} nombre="Cerro Renca" lado="izq" />
          {e.ruta.cuadras.map((c, i) => {
            const x = CERRO + i * SEG + SEG / 2;
            if (e.acto >= 2) return <Arbol key={c.h} x={x} s={crece(i)} flores={i % 2 === 1} />;
            return esArbol(c, v.sin_copa_pct) ? <Arbol key={c.h} x={x} s={0.8} flores={false} /> : <Edificio key={c.h} x={x} c={c} />;
          })}
          <Cerro x={CERRO + n * SEG} nombre="Cerro San Cristóbal" lado="der" />
          {e.acto === 1 && e.calor > 0.3 && [0, 1, 2, 3, 4, 5].map((k) => (
            <path key={k} d={`M${cam + 140 + k * 170} ${H - 120} q 12 -16 0 -32 q -12 -16 0 -32`} stroke="#FFF4DC" strokeWidth={3} fill="none"
              opacity={Math.max(0, (e.calor - 0.3) * (0.5 + 0.5 * Math.sin(t / 200 + k)))} />
          ))}
        </g>
        <Ave y={y} aleteo={t / (e.acto === 1 ? 45 + cansancio * 40 : 32)} cansancio={cansancio} />
        {e.contador && (
          <g>
            <rect x={28} y={26} width={430} height={54} rx={27} fill="rgba(246,239,210,0.92)" />
            <text x={50} y={62} fontSize="24" fontWeight="700" fill={e.acto === 1 && e.racha >= 6 ? "#96261C" : "#2F4520"}>{e.contador}</text>
          </g>
        )}
        <g className="corto-texto" key={e.texto}>
          <rect x={28} y={H - 108 - subY} width={W - 56} height={82 + subY} rx={20} fill="rgba(34,40,26,0.72)" />
          <text x={56} y={H - 58 - subY} fontSize="31" fontFamily="var(--f-display), serif" fill="#F6EFD2">{e.texto}</text>
          {e.sub && <text x={56} y={H - 58 - subY + 40} fontSize="19" fill="#E4DFCC">{e.sub}</text>}
        </g>
      </svg>
      <div className="corto-ctl">
        <button type="button" className="pill llena" onClick={() => (andando ? pausar() : reproducir(t >= total ? 0 : t))}>
          {andando ? "Pausar" : t >= total ? "Ver de nuevo" : t > 0 ? "Seguir" : "Ver el viaje"}
        </button>
        <div className="corto-barra" aria-hidden="true"><i style={{ width: `${total ? (100 * t) / total : 0}%` }} /></div>
      </div>
      <p className="nota">La ciudad del primer viaje es la real: en línea recta entre los dos cerros, cada edificio es una cuadra con menos de {v.sin_copa_pct} % de copa y cada árbol una con más ({v.recta.sin_arboles_max} seguidas sin árboles). El segundo viaje va por la ruta de menor costo para aves y supone el corredor ya plantado: es lo que propone Viridis, no una medición. Registros del picaflor chico (<i>{v.especie}</i>): GBIF.</p>
    </div>
  );
}
