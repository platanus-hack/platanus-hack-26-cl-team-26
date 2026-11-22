"use client";
import { useEffect, useRef, useState } from "react";
import { formato, menosMovimiento } from "./movimiento";

// El viaje del picaflor chico del Cerro Renca al Cerro San Cristóbal (viaje_picaflor.py → public/data/viaje.json).
// Cada cuadrado es una cuadra del camino fuera de los dos cerros, coloreada por su copa de árboles.
type Cuadra = { h: string; copa: number; parque: boolean };
type Ruta = { cuadras: Cuadra[]; km: number; sin_arboles_max: number; sin_arboles: number; copa_media: number };
type Viaje = {
  especie: string; nombre: string; desde: number; registros_santiago: number; origen: string; destino: string;
  sin_copa_pct: number; recta: Ruta; corredor: Ruta;
};

const GRIS = "#C9C2AE";
const VERDES = ["#C5CDA6", "#8C9A63", "#4F6E31"];
const PLANTADA = "#62A83C";
const MS_POR_CUADRA = 260;

let viajeCache: Promise<Viaje | null> | null = null;

function colorCuadra(c: Cuadra, umbral: number) {
  if (!c.parque && c.copa < umbral) return GRIS;
  return c.parque || c.copa >= 25 ? VERDES[2] : c.copa >= 15 ? VERDES[1] : VERDES[0];
}

// Silueta simple de un picaflor (cuerpo, ala, cola y pico largo), dibujada en SVG.
function Picaflor({ size = 42 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <path d="M22 18 L39 15.5 L22 20.5 Z" fill="#22281A" />
      <ellipse cx="16" cy="20" rx="8" ry="5.2" fill="#2E7D4F" />
      <circle cx="21" cy="18" r="3.6" fill="#2E7D4F" />
      <circle cx="22.2" cy="17.2" r="0.9" fill="#F6EFD2" />
      <path d="M15 17 Q10 6 4 9 Q9 14 13 19 Z" fill="#4FA46C" />
      <path d="M9 21 L1 27 L4 21 L1 16 Z" fill="#1F5A3A" />
      <path d="M17 23 Q19 25.5 22 23.5" stroke="#C0392B" strokeWidth="2" fill="none" />
    </svg>
  );
}

function Cinta({ titulo, ruta, umbral, plantada, progreso, sin, activa }: {
  titulo: string; ruta: Ruta; umbral: number; plantada?: boolean; progreso: number; sin: number; activa: boolean;
}) {
  const n = ruta.cuadras.length;
  return (
    <div className="viaje-fila">
      <div className="viaje-cab">
        <b>{titulo}</b>
        <span className="num">{n} cuadras · {formato(ruta.km, 1)} km</span>
      </div>
      <div className="viaje-cinta" role="img" aria-label={`${titulo}: ${n} cuadras, ${sin} seguidas sin árboles como máximo`}>
        <span className="viaje-cerro">Renca</span>
        <div className="viaje-cuadras">
          {ruta.cuadras.map((c, i) => (
            <i key={c.h} style={{ background: plantada ? PLANTADA : colorCuadra(c, umbral), opacity: i < progreso * n ? 1 : 0.35 }} />
          ))}
          {activa && <div className="viaje-ave" style={{ left: `calc(${progreso * 100}% - 21px)` }}><Picaflor /></div>}
        </div>
        <span className="viaje-cerro">San Cristóbal</span>
      </div>
      <p className="viaje-dato"><b className="num">{sin}</b> {sin === 1 ? "cuadra seguida" : "cuadras seguidas"} sin un árbol, como máximo</p>
    </div>
  );
}

export default function ViajePicaflor() {
  const [v, setV] = useState<Viaje | null>(null);
  const [paso, setPaso] = useState(0);        // 0: listo; 1, 2, 3: vuela por esa cinta; 4: terminó
  const [prog, setProg] = useState([0, 0, 0]);
  const raf = useRef(0);
  const ref = useRef<HTMLDivElement>(null);
  const visto = useRef(false);

  useEffect(() => {
    viajeCache ??= fetch("/data/viaje.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    let vivo = true;
    viajeCache.then((d) => vivo && setV(d));
    return () => { vivo = false; cancelAnimationFrame(raf.current); };
  }, []);

  // Las tres cintas, una después de la otra; con menos movimiento, todas completas de una.
  function volar() {
    if (!v) return;
    cancelAnimationFrame(raf.current);
    if (menosMovimiento()) { setProg([1, 1, 1]); setPaso(4); return; }
    const largos = [v.recta, v.corredor, v.corredor].map((r) => r.cuadras.length * MS_POR_CUADRA);
    setProg([0, 0, 0]);
    let k = 0, t0 = performance.now();
    setPaso(1);
    const tic = (t: number) => {
      const f = Math.min(1, (t - t0) / largos[k]);
      setProg((p) => p.map((x, i) => (i === k ? f : x)));
      if (f < 1) { raf.current = requestAnimationFrame(tic); return; }
      k += 1;
      if (k === 3) { setPaso(4); return; }
      setPaso(k + 1);
      t0 = t + 500;
      raf.current = requestAnimationFrame(function espera(t2) { if (t2 < t0) { raf.current = requestAnimationFrame(espera); return; } tic(t2); });
    };
    raf.current = requestAnimationFrame(tic);
  }

  // Parte solo la primera vez que la sección se ve.
  useEffect(() => {
    if (!v || !ref.current) return;
    const ob = new IntersectionObserver(([e]) => { if (e.isIntersecting && !visto.current) { visto.current = true; volar(); } }, { threshold: 0.12 });
    ob.observe(ref.current);
    return () => ob.disconnect();
  }, [v]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={ref}>
      <div className="b-cab escalon">
        <h2>El viaje <em>del picaflor</em></h2>
        <p>El picaflor chico es el colibrí que más se ve en Santiago{v ? `: ${formato(v.registros_santiago)} registros desde ${v.desde}` : ""}. Para cruzar la ciudad del Cerro Renca al Cerro San Cristóbal necesita árboles donde descansar y flores donde comer. Hoy, el cemento se los corta.</p>
      </div>
      {!v ? <div className="sk" style={{ height: 260 }} /> : (
        <div className="viaje">
          <Cinta titulo="Hoy, en línea recta" ruta={v.recta} umbral={v.sin_copa_pct} progreso={prog[0]} sin={v.recta.sin_arboles_max} activa={paso >= 1} />
          <Cinta titulo="Hoy, por donde más árboles quedan" ruta={v.corredor} umbral={v.sin_copa_pct} progreso={prog[1]} sin={v.corredor.sin_arboles_max} activa={paso >= 2} />
          <Cinta titulo="Con el corredor de Viridis" ruta={v.corredor} umbral={v.sin_copa_pct} plantada progreso={prog[2]} sin={0} activa={paso >= 3} />
          <div className="viaje-pie">
            <button type="button" className="pill llena" onClick={volar} disabled={paso > 0 && paso < 4}>{paso > 0 && paso < 4 ? "Volando…" : "Volar de nuevo"}</button>
            <div className="leyenda">
              <span><i className="cuadro" style={{ background: GRIS }} />Menos de {v.sin_copa_pct} % de copa: sin árboles</span>
              <span><i className="cuadro" style={{ background: VERDES[1] }} />Con copa o parque</span>
              <span><i className="cuadro" style={{ background: PLANTADA }} />Plantada por el corredor</span>
            </div>
          </div>
          <p className="nota">Cada cuadrado es una cuadra del camino fuera de los dos cerros. La copa sale de nuestro modelo sobre Sentinel-2; la ruta «por donde más árboles quedan» es la de menor costo para aves (la misma del perfil Aves), y los registros del picaflor (<i>{v.especie}</i>) son de GBIF. La última cinta supone que el corredor se planta completo: es lo que propone Viridis, no una medición.</p>
        </div>
      )}
    </div>
  );
}
