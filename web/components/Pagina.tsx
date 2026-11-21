"use client";
import { useEffect, useMemo, useState } from "react";
import type { ExpressionSpecification, LngLatBoundsLike } from "maplibre-gl";
import { cellToBoundary, cellToLatLng } from "h3-js";
import MapaHex, { type Capa } from "./MapaHex";
import Cifra from "./Cifra";
import { formato, useRevela, useVisible } from "./movimiento";
import { solveCorridor, urgencia, type Barrio, type Hex, type Resultado } from "@/lib/optimizador";

type Cifras = {
  lst_c_media: Record<string, number>;
  copa_modelo_pct_medio: Record<string, number>;
  urgencia_media: Record<string, number>;
  corredor: { tramos: number };
  lst_fecha: string;
  lst_fecha_ultima: string;
  referencia: Resultado;
};
type Vivo = { barrios: Barrio[]; sensores: { source: string; medido_en: string }[] };
type Historico = { meses: string[]; escenas_landsat: number; escenas_sentinel2: number; lst: Record<string, (number | null)[]> };

const COMUNAS = ["Cerro Navia", "Providencia"] as const;
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const fechaLarga = (iso: string) => { const [a, m, d] = iso.split("-").map(Number); return `${d} de ${MESES_LARGOS[m - 1]} de ${a}`; };
const esVerano = (ym: string) => [12, 1, 2].includes(Number(ym.slice(5)));
const mesCorto = (ym: string) => { const [a, m] = ym.split("-").map(Number); return `${MESES[m - 1]} ${a}`; };

// Hora local de Santiago, igual en servidor y navegador (evita diferencias de formato al hidratar).
const horaSantiago = (iso: string) => {
  const p = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "America/Santiago" }).formatToParts(new Date(iso));
  return `${p.find((x) => x.type === "hour")?.value}:${p.find((x) => x.type === "minute")?.value}`;
};

const VERDE = ["#EFE9DA", "#C5CDA6", "#8C9A63", "#4F6E31"];
const OCRE = ["#F1E9D6", "#DEBE80", "#966222"];
const GRAD_VERDE = `linear-gradient(90deg,${VERDE.join(",")})`;
const GRAD_OCRE = `linear-gradient(90deg,${OCRE.join(",")})`;
const escalaOcre = (prop: string): ExpressionSpecification =>
  ["interpolate", ["linear"], ["coalesce", ["get", prop], 32], 32, OCRE[0], 37, OCRE[1], 42, OCRE[2]];
const escalaVerde = (prop: string, max: number): ExpressionSpecification =>
  ["interpolate", ["linear"], ["get", prop], 0, VERDE[0], max * 0.45, VERDE[1], max * 0.72, VERDE[2], max, VERDE[3]];

const CAPAS_AHORA: Capa[] = [
  { id: "calor", color: escalaOcre("t") },
  { id: "copa", color: escalaVerde("a", 25) },
  { id: "personas", color: escalaVerde("n", 2500) },
];
const CAPAS_PLAN: Capa[] = [{ id: "urg", color: ["case", ["get", "k"], "#B7C298", escalaVerde("u", 0.85)] }];
// En el histórico la escala se ajusta al rango elegido (todo el año promedia ~25 °C, los veranos ~37 °C).
const CAPAS_HIST: Capa[] = [{ id: "hist", color: ["interpolate", ["linear"], ["coalesce", ["get", "hn"], 0], 0, OCRE[0], 0.5, OCRE[1], 1, OCRE[2]] }];
const LEYENDA: Record<string, [string, string]> = {
  calor: [GRAD_OCRE, "Suelo de 32 °C a 42 °C o más"],
  copa: [GRAD_VERDE, "Copa de árboles, de 0 % a 25 % o más"],
  personas: [GRAD_VERDE, "Personas por cuadra, de 0 a 2.500"],
};
const NOMBRE_CAPA: Record<string, string> = { calor: "Calor del suelo", copa: "Copa de árboles", personas: "Personas" };

function anillo(h: string) {
  const b = cellToBoundary(h, true);
  return [...b, b[0]];
}

function encuadreDe(hexes: Hex[]): LngLatBoundsLike {
  let w = 180, s = 90, e = -180, n = -90;
  for (const x of hexes) {
    const [lat, lng] = cellToLatLng(x.h);
    w = Math.min(w, lng); e = Math.max(e, lng); s = Math.min(s, lat); n = Math.max(n, lat);
  }
  return [[w - 0.006, s - 0.006], [e + 0.006, n + 0.006]];
}

function Seccion({ id, alt, children }: { id: string; alt?: boolean; children: React.ReactNode }) {
  const ref = useRevela<HTMLElement>();
  return (
    <section ref={ref} id={id} className={`b-sec b-pad revela${alt ? " alt" : ""}`}>
      <div className="b-in">{children}</div>
    </section>
  );
}

function Rama() {
  const hojas = [
    ["M100 95 C 70 100, 45 85, 40 70 C 65 60, 90 70, 100 95Z", "#5E7F3E"],
    ["M150 150 C 150 110, 170 90, 190 85 C 195 120, 180 140, 150 150Z", "#A9BE88"],
    ["M170 185 C 135 195, 110 185, 100 165 C 130 155, 155 160, 170 185Z", "#4F6E31"],
    ["M225 245 C 228 205, 250 185, 272 182 C 272 218, 255 238, 225 245Z", "#8FA86B"],
    ["M245 285 C 210 300, 182 290, 172 270 C 205 258, 230 265, 245 285Z", "#A9BE88"],
    ["M295 360 C 300 320, 325 300, 345 298 C 343 335, 325 352, 295 360Z", "#5E7F3E"],
    ["M310 400 C 275 415, 248 405, 238 385 C 270 372, 296 380, 310 400Z", "#8FA86B"],
    ["M350 470 C 358 432, 382 415, 404 414 C 398 450, 378 466, 350 470Z", "#A9BE88"],
    ["M365 520 C 330 530, 305 518, 297 498 C 330 488, 352 497, 365 520Z", "#4F6E31"],
  ];
  return (
    <svg className="rama" aria-hidden="true" viewBox="0 0 420 620">
      <path className="tallo" d="M20 10 C 120 120, 220 260, 300 380 S 390 560, 410 615" fill="none" stroke="#7A6A4F" strokeWidth="3" strokeLinecap="round" />
      {hojas.map(([d, c], i) => <path key={i} className="hoja" d={d} fill={c} style={{ "--i": i } as React.CSSProperties} />)}
    </svg>
  );
}

const Hoja = () => (
  <svg aria-hidden="true" viewBox="0 0 32 32"><path d="M5 27 C 8 14, 16 6, 28 4 C 27 16, 19 25, 5 27Z" fill="#4F6E31" /><path d="M5 27 L 20 12" stroke="#EFE9DA" strokeWidth="1.6" fill="none" /></svg>
);

export default function Pagina({ hexes, vivo, cifras }: { hexes: Hex[]; vivo: Vivo; cifras: Cifras }) {
  const anillos = useMemo(() => hexes.map((x) => anillo(x.h)), [hexes]);
  const coleccion = (props: (x: Hex, i: number) => Record<string, unknown>): GeoJSON.FeatureCollection => ({
    type: "FeatureCollection",
    features: hexes.map((x, i) => ({ type: "Feature", id: i, properties: { i, ...props(x, i) }, geometry: { type: "Polygon", coordinates: [anillos[i]] } })),
  });

  const encuadres = useMemo(() => ({
    Ambas: encuadreDe(hexes),
    "Cerro Navia": encuadreDe(hexes.filter((x) => x.c === "Cerro Navia")),
    Providencia: encuadreDe(hexes.filter((x) => x.c === "Providencia")),
  }), [hexes]);

  // Aire en vivo por comuna: el barrio (res 7) con dato más reciente.
  const aire = useMemo(() => {
    const out: Record<string, { t: number; conf: string; hora: string } | null> = {};
    for (const c of COMUNAS) {
      const padres = new Set(hexes.filter((x) => x.c === c).map((x) => x.p));
      const b = vivo.barrios.filter((y) => padres.has(y.p) && y.t != null).sort((x, y) => (y.medido ?? "").localeCompare(x.medido ?? ""))[0];
      out[c] = b ? {
        t: b.t as number, conf: b.conf,
        hora: b.medido ? horaSantiago(b.medido) : "",
      } : null;
    }
    return out;
  }, [hexes, vivo]);
  const aireOk = vivo.barrios.some((b) => (b.conf === "alta" || b.conf === "media") && b.t != null);

  // ---- El calor ahora
  const [capa, setCapa] = useState("calor");
  const [foco, setFoco] = useState<keyof typeof encuadres>("Ambas");
  const [sel, setSel] = useState<number | null>(null);
  const datosAhora = useMemo(() => coleccion((x) => ({ t: x.t, a: x.a, n: x.n })), [hexes, anillos]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Planificar
  const [pesos, setPesos] = useState({ calor: 40, arbol: 40, pers: 20, km: 3 });
  const [calculado, setCalculado] = useState({ calor: 40, arbol: 40, pers: 20, km: 3 });
  const [res, setRes] = useState<Resultado>(cifras.referencia);
  const [urg, setUrg] = useState<number[]>(() => hexes.map((x) => x.u));
  const [calculando, setCalculando] = useState(false);
  const esReferencia = calculado.calor === 40 && calculado.arbol === 40 && calculado.pers === 20 && calculado.km === 3;
  const pendiente = JSON.stringify(pesos) !== JSON.stringify(calculado);
  const total = pesos.calor + pesos.arbol + pesos.pers || 1;

  function recalcular() {
    setCalculando(true);
    requestAnimationFrame(() => {
      const p = { ...pesos };
      const def = p.calor === 40 && p.arbol === 40 && p.pers === 20 && p.km === 3;
      const w = p.calor + p.arbol + p.pers > 0 ? [p.calor, p.arbol, p.pers] : [40, 40, 20];
      setUrg(urgencia(hexes, w[0], w[1], w[2], vivo.barrios));
      setRes(def ? cifras.referencia : solveCorridor(hexes, p.km, w[0], w[1], w[2], vivo.barrios));
      setCalculado(p);
      setCalculando(false);
    });
  }

  const datosPlan = useMemo(() => coleccion((x, i) => ({ u: urg[i], k: x.k })), [urg, anillos]); // eslint-disable-line react-hooks/exhaustive-deps
  const corredor = useMemo<GeoJSON.FeatureCollection>(() => {
    const idx = new Map(hexes.map((x, i) => [x.h, i]));
    return {
      type: "FeatureCollection",
      features: res.tramos.flatMap((tramo, t) => tramo.map((h) => ({
        type: "Feature" as const, properties: { h3: h, tramo: t + 1, comuna: hexes[idx.get(h)!]?.c },
        geometry: { type: "Polygon" as const, coordinates: [anillos[idx.get(h)!] ?? anillo(h)] },
      }))),
    };
  }, [res, hexes, anillos]);
  const comunasCorredor = [...new Set(corredor.features.map((f) => f.properties?.comuna as string))].sort();
  // El mapa del plan se acerca a la comuna donde cae el corredor; si cae en las dos, muestra ambas.
  const focoPlan = comunasCorredor.length === 1 ? (comunasCorredor[0] as keyof typeof encuadres) : "Ambas";

  function exportar() {
    const blob = new Blob([JSON.stringify(corredor)], { type: "application/geo+json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `corredor_${formato(calculado.km, 1).replace(",", "_")}km.geojson`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---- Histórico (se pide al acercarse a la sección)
  const [refHist, verHist] = useVisible<HTMLDivElement>("400px");
  const [hist, setHist] = useState<Historico | null>(null);
  const [desde, setDesde] = useState(12);
  const [soloVerano, setSoloVerano] = useState(false);
  useEffect(() => {
    if (verHist && !hist) fetch("/data/historico.json").then((r) => r.json()).then(setHist).catch(() => {});
  }, [verHist, hist]);
  const mediaMes = useMemo(() => {
    if (!hist) return [];
    return hist.meses.map((_, j) => {
      const v = Object.values(hist.lst).map((f) => f[j]).filter((x): x is number => x != null);
      return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
    });
  }, [hist]);
  const promHex = useMemo(() => hexes.map((x) => {
    const f = hist?.lst[x.h];
    const v = f ? f.filter((y, j): y is number => y != null && j >= desde && (!soloVerano || esVerano(hist!.meses[j]))) : [];
    return v.length ? v.reduce((s, y) => s + y, 0) / v.length : null;
  }), [hist, desde, soloVerano, hexes]);
  const escalaHist = useMemo(() => {
    const v = promHex.filter((x): x is number => x != null).sort((a, b) => a - b);
    return v.length ? [v[Math.floor(v.length * 0.02)], v[Math.ceil(v.length * 0.98) - 1]] : [0, 1];
  }, [promHex]);
  const datosHist = useMemo(() => coleccion((_, i) => ({
    hn: promHex[i] == null ? null : Math.min(1, Math.max(0, ((promHex[i] as number) - escalaHist[0]) / (escalaHist[1] - escalaHist[0] || 1))),
  })), [promHex, escalaHist, anillos]); // eslint-disable-line react-hooks/exhaustive-deps
  const promComuna = (c: string) => {
    const v = hexes.flatMap((x, i) => (x.c === c && promHex[i] != null ? [promHex[i] as number] : []));
    return v.length ? v.reduce((s, y) => s + y, 0) / v.length : 0;
  };
  const lo = Math.min(...mediaMes.filter((x): x is number => x != null));
  const hi = Math.max(...mediaMes.filter((x): x is number => x != null));

  const detalle = sel == null ? null : hexes[sel];

  return (
    <main className="b">
      <p className="banda">Comunas piloto: Cerro Navia y Providencia. Calor de la escena Landsat del {fechaLarga(cifras.lst_fecha)}.</p>
      <header className="b-pad"><div className="b-in">
        <a className="marca" href="#inicio"><Hoja />VERDEH3</a>
        <nav aria-label="Secciones"><a href="#ahora">El calor ahora</a><a href="#planificar">Planificar</a><a href="#historico">Histórico</a><a href="#fuentes">Fuentes</a></nav>
      </div></header>

      <section className="b-hero b-pad" id="inicio">
        <Rama />
        <div className="b-in">
          <h1>Sombra donde más falta</h1>
          <p>Calor del suelo, copa de árboles y personas, cuadra por cuadra, para decidir por dónde plantar el próximo corredor verde. <em>Cada metro de sombra, donde más alivia.</em></p>
          <div className="grupo" style={{ gap: 12 }}>
            <a className="pill llena grande" href="#planificar">Planificar un corredor</a>
            <a className="pill grande" href="#ahora">Ver el calor ahora</a>
          </div>
        </div>
      </section>

      <Seccion id="ahora" alt>
        <div className="b-cab escalon">
          <h2>El calor ahora</h2>
          <div className="grupo" role="group" aria-label="Capa del mapa">
            {CAPAS_AHORA.map((c) => <button key={c.id} type="button" className="pill" aria-pressed={capa === c.id} onClick={() => setCapa(c.id)}>{NOMBRE_CAPA[c.id]}</button>)}
          </div>
        </div>
        <div className="grupo escalon" role="group" aria-label="Encuadre del mapa" style={{ "--i": 1 } as React.CSSProperties}>
          {(["Ambas", ...COMUNAS] as const).map((c) => <button key={c} type="button" className="pill" style={{ minHeight: 40, fontSize: 14 }} aria-pressed={foco === c} onClick={() => setFoco(c)}>{c === "Ambas" ? "Las dos comunas" : c}</button>)}
        </div>
        <div className="escalon" style={{ "--i": 2 } as React.CSSProperties}>
          <MapaHex datos={datosAhora} capas={CAPAS_AHORA} activa={capa} encuadre={encuadres[foco]} alElegir={setSel} etiqueta={`Mapa de ${NOMBRE_CAPA[capa].toLowerCase()} por cuadra. Elige una para ver sus datos.`} />
        </div>
        <div className="leyenda">
          <span><i className="barra" style={{ background: LEYENDA[capa][0] }} />{LEYENDA[capa][1]}</span>
          <span className="detalle num" aria-live="polite">{detalle
            ? `${detalle.c}${detalle.k ? ", parque" : ""}: suelo ${formato(detalle.t, 1)} °C, copa ${formato(detalle.a, 1)} %, ${formato(detalle.n)} personas.`
            : "Toca una cuadra para ver sus datos."}</span>
        </div>
        <div className="comunas">
          {COMUNAS.map((c, k) => (
            <div key={c} className="comuna escalon" style={{ "--i": 3 + k } as React.CSSProperties}>
              <b>{c}</b>
              <div className="datos">
                <span><span className="grande"><Cifra valor={cifras.lst_c_media[c]} dec={1} /></span> °C de suelo</span>
                <span><span className="grande"><Cifra valor={cifras.copa_modelo_pct_medio[c]} dec={1} /></span> % de copa</span>
              </div>
              <span className="num">{aire[c]
                ? `Aire ${formato(aire[c]!.t, 1)} °C a las ${aire[c]!.hora}, confianza ${aire[c]!.conf}${aire[c]!.conf === "baja" ? ": no entra al índice" : ""}.`
                : "Sin sensor de aire cerca: el calor sale solo del satélite."}</span>
            </div>
          ))}
        </div>
        <p className="nota">El aire en vivo solo entra al índice de calor con confianza alta o media, y pesa 40 % frente a 60 % del suelo. {aireOk ? "Hoy sí hay barrios con dato confiable." : `Hoy hay ${vivo.sensores.length === 1 ? "un sensor" : `${vivo.sensores.length} sensores`} cerca y ninguno llega a confianza media, así que el mapa usa solo Landsat.`}</p>
      </Seccion>

      <Seccion id="planificar">
        <div className="b-cab escalon"><h2>Planificar</h2><p>Mueve los pesos y el presupuesto; el corredor se traza de parque a parque por las cuadras más urgentes.</p></div>
        <div className="b-controles escalon" style={{ "--i": 1 } as React.CSSProperties}>
          {([["calor", "Calor"], ["arbol", "Falta de árboles"], ["pers", "Personas cerca"]] as const).map(([k, nombre]) => (
            <div className="peso" key={k}>
              <label htmlFor={`p-${k}`}><span>{nombre}</span><b>{Math.round((100 * pesos[k]) / total)} %</b></label>
              <input id={`p-${k}`} type="range" min={0} max={100} step={5} value={pesos[k]} onChange={(e) => setPesos({ ...pesos, [k]: Number(e.target.value) })} />
            </div>
          ))}
          <div className="peso">
            <label htmlFor="p-km"><span>Presupuesto</span><b>{formato(pesos.km, pesos.km % 1 ? 1 : 0)} km</b></label>
            <input id="p-km" type="range" min={1} max={20} step={0.5} value={pesos.km} onChange={(e) => setPesos({ ...pesos, km: Number(e.target.value) })} />
          </div>
        </div>
        {pendiente && <p className="aviso" role="status">Las cifras son de {Math.round((100 * calculado.calor) / (calculado.calor + calculado.arbol + calculado.pers || 1))} / {Math.round((100 * calculado.arbol) / (calculado.calor + calculado.arbol + calculado.pers || 1))} / {Math.round((100 * calculado.pers) / (calculado.calor + calculado.arbol + calculado.pers || 1))} y {formato(calculado.km, calculado.km % 1 ? 1 : 0)} km. Presiona Recalcular corredor para ver el nuevo trazado.</p>}
        <div className="b-plan">
          <div className="izq escalon" style={{ "--i": 2 } as React.CSSProperties}>
            <MapaHex datos={datosPlan} capas={CAPAS_PLAN} activa="urg" corredor={corredor} encuadre={encuadres[focoPlan] ?? encuadres.Ambas} etiqueta="Corredor propuesto sobre la urgencia de cada cuadra" />
            <div className="leyenda">
              <span><i className="barra" style={{ background: GRAD_VERDE }} />Urgencia</span>
              <span><i className="cuadro" style={{ background: "#22301A" }} />Corredor</span>
              <span><i className="cuadro" style={{ background: "#B7C298" }} />Parque</span>
            </div>
          </div>
          <div className="cifras">
            <div className="cifra escalon" style={{ "--i": 3 } as React.CSSProperties}>
              <b><Cifra valor={res.personas_cubiertas} /></b>
              <span>personas viven junto al corredor. Con un trazado al azar del mismo largo serían <strong className="num"><Cifra valor={res.personas_azar} /></strong>.</span>
            </div>
            <div className="cifra escalon" style={{ "--i": 4 } as React.CSSProperties}>
              <b><Cifra valor={res.length_km} dec={2} sufijo={"\u00a0km"} /></b>
              <span>en {res.tramos.length} {res.tramos.length === 1 ? "tramo" : "tramos"} y {res.hexes.length} cuadras{comunasCorredor.length ? `, en ${comunasCorredor.join(" y ")}` : ""}. Urgencia cubierta {formato(res.urgencia_cubierta, 3)}, contra {formato(res.urgencia_azar, 3)} al azar.</span>
            </div>
            <div className="grupo escalon" style={{ "--i": 5 } as React.CSSProperties}>
              <button type="button" className="pill llena" onClick={recalcular} disabled={calculando}>{calculando ? "Calculando…" : "Recalcular corredor"}</button>
              <button type="button" className="pill" onClick={exportar} disabled={!res.hexes.length}>Exportar tramos</button>
            </div>
            <p className="nota">{esReferencia
              ? "Cifras de optimizer.py con los pesos por defecto."
              : "Trazado calculado en el navegador con el mismo método que optimizer.py. El azar usa otro generador, así que su cifra puede variar un poco."}</p>
          </div>
        </div>
      </Seccion>

      <Seccion id="historico" alt>
        <div className="b-cab escalon"><h2>Histórico</h2><p>Elige desde qué mes promediar el calor del suelo: {hist ? `${hist.escenas_landsat} escenas Landsat y ${hist.escenas_sentinel2} Sentinel-2` : "escenas Landsat y Sentinel-2"}, de enero de 2023 a noviembre de 2026.</p></div>
        <div ref={refHist} className="escalon" style={{ "--i": 1, display: "flex", flexDirection: "column", gap: 10 } as React.CSSProperties}>
          <div className="b-meses" role="group" aria-label="Mes desde el que se promedia">
            {(hist?.meses ?? Array.from({ length: 47 }, (_, j) => `${2023 + Math.floor(j / 12)}-${String((j % 12) + 1).padStart(2, "0")}`)).map((m, j) => {
              const v = mediaMes[j];
              const verano = esVerano(m);
              const alto = v == null || !hist ? 8 : 14 + (86 * (v - lo)) / (hi - lo || 1);
              return (
                <button key={m} type="button" aria-pressed={j === desde} onClick={() => setDesde(j)}
                  aria-label={`${mesCorto(m)}${v != null ? `, suelo medio ${formato(v, 1)} °C` : ", sin escena Landsat"}`}
                  title={`${mesCorto(m)}${v != null ? ` · ${formato(v, 1)} °C` : " · sin escena"}`}>
                  <span style={{ height: `${alto}%`, background: j < desde || (soloVerano && !verano) ? "#D6D9BF" : verano ? "#4F6E31" : "#8C9A63", outline: j === desde ? "2px solid #22281A" : undefined, outlineOffset: 1 }} />
                </button>
              );
            })}
          </div>
          <div className="b-ejes num"><span>ene 2023</span><span>ene 2024</span><span>ene 2025</span><span>ene 2026</span><span>nov 2026</span></div>
        </div>
        <div className="b-hist">
          <div className="izq escalon" style={{ "--i": 2 } as React.CSSProperties}>
            <MapaHex datos={datosHist} capas={CAPAS_HIST} activa="hist" encuadre={encuadres.Ambas} etiqueta="Promedio del calor del suelo por cuadra en el rango elegido" />
            <div className="leyenda" style={{ marginTop: 10 }}><span><i className="barra" style={{ background: GRAD_OCRE }} /><span className="num">Suelo medio de {formato(escalaHist[0], 1)} °C a {formato(escalaHist[1], 1)} °C</span></span></div>
          </div>
          <div className="cifras">
            <div className="grupo" role="group" aria-label="Meses a promediar">
              <button type="button" className="pill" style={{ minHeight: 40, fontSize: 14 }} aria-pressed={!soloVerano} onClick={() => setSoloVerano(false)}>Todo el año</button>
              <button type="button" className="pill" style={{ minHeight: 40, fontSize: 14 }} aria-pressed={soloVerano} onClick={() => setSoloVerano(true)}>Solo veranos</button>
            </div>
            <p style={{ margin: 0, fontSize: 16, color: "var(--oliva-osc)" }}>Rango elegido: <b>{hist ? mesCorto(hist.meses[desde]) : "ene 2024"} a nov 2026</b>. Las barras altas son los veranos, que son los que usa el índice de calor.</p>
            {COMUNAS.map((c, k) => (
              <div key={c} className="cifra escalon" style={{ "--i": 3 + k } as React.CSSProperties}>
                <b>{hist ? <Cifra valor={promComuna(c)} dec={1} sufijo={"\u00a0°C"} duracion={700} /> : "…"}</b>
                <span>suelo medio en {c}, {soloVerano ? "solo veranos" : "todo el año"}.</span>
              </div>
            ))}
          </div>
        </div>
      </Seccion>

      <footer className="b-pad revela visto" id="fuentes"><div className="b-in">
        <h2>Fuentes</h2>
        <p><b>Calor del suelo.</b> Landsat 8 y 9, Collection 2 Level 2 (USGS), vía Microsoft Planetary Computer. Escena del índice: {fechaLarga(cifras.lst_fecha)}; la más reciente, {fechaLarga(cifras.lst_fecha_ultima)}.</p>
        <p><b>Copa de árboles.</b> Modelo propio sobre Sentinel-2 de febrero de 2026, entrenado con la altura de copa de Meta y WRI (r = 0,92 por cuadra en comunas que el modelo no vio).</p>
        <p><b>Personas.</b> Censo 2024 del INE por manzana, más cercanía a colegios, salud, metro y paraderos de OpenStreetMap.</p>
        <p><b>Aire en vivo.</b> DMC, SINCA y Sensor.Community, agrupados por barrio (H3 resolución 7). Mapa base: CARTO y OpenStreetMap.</p>
      </div></footer>
    </main>
  );
}
