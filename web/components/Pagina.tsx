"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ExpressionSpecification, LngLatBoundsLike } from "maplibre-gl";
import { cellToBoundary, cellsToDirectedEdge, directedEdgeToBoundary, getResolution, gridDisk, latLngToCell, polygonToCellsExperimental, POLYGON_TO_CELLS_FLAGS } from "h3-js";
import MapaHex, { type Capa, type Foco } from "./MapaHex";
import Cifra from "./Cifra";
import FiltroComunas from "./FiltroComunas";
import { formato, useRevela, useVisible } from "./movimiento";
import { historico, useTerreno, type Captura, type Estado, type HexCols, type InfoComunas } from "@/lib/terreno";

type Serie = { meses: string[]; escenas_landsat: number; escenas_sentinel2: number; media_mes: (number | null)[]; lst_fecha_ultima: string };

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const fechaLarga = (iso: string) => { const [a, m, d] = iso.split("-").map(Number); return `${d} de ${MESES_LARGOS[m - 1]} de ${a}`; };
const esVerano = (ym: string) => [12, 1, 2].includes(Number(ym.slice(5)));
const mesCorto = (ym: string) => { const [a, m] = ym.split("-").map(Number); return `${MESES[m - 1]} ${a}`; };
const sinNulos = (xs: (number | null)[]) => xs.filter((x): x is number => x != null);
const media = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0);
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const est = (i: number) => ({ "--i": i } as React.CSSProperties);

// Min-max con percentiles 2 y 98, como optimizer._norm.
function norm(xs: (number | null)[]) {
  const v = sinNulos(xs).sort((a, b) => a - b);
  if (!v.length) return xs.map(() => null);
  const p = (q: number) => { const i = (v.length - 1) * q, lo = Math.floor(i); return v[lo] + (v[Math.ceil(i)] - v[lo]) * (i - lo); };
  const lo = p(0.02), hi = p(0.98);
  return xs.map((x) => (x == null ? null : hi > lo ? Math.min(1, Math.max(0, (x - lo) / (hi - lo))) : 0));
}

const VERDE = ["#EFE9DA", "#C5CDA6", "#8C9A63", "#4F6E31"];
const OCRE = ["#F1E9D6", "#DEBE80", "#966222"];
const grad = (c: string[]) => `linear-gradient(90deg,${c.join(",")})`;
const escala = (prop: string, cols: string[], lo: number, hi: number): ExpressionSpecification => {
  const paso = (hi - lo) / (cols.length - 1);
  return ["interpolate", ["linear"], ["coalesce", ["get", prop], lo], ...cols.flatMap((c, i) => [lo + paso * i, c])] as ExpressionSpecification;
};

const CAPAS_AHORA: Capa[] = [
  { id: "calor", color: escala("calor", OCRE, 0, 1) },
  { id: "copa", color: escala("copa", VERDE, 0, 25) },
  { id: "personas", color: escala("personas", VERDE, 0, 1) },
];
const NOMBRE_CAPA: Record<string, string> = { calor: "Calor", copa: "Copa de árboles", personas: "Personas" };
const LEYENDA: Record<string, [string, string]> = {
  calor: [grad(OCRE), "Índice de calor: 60 % suelo y 40 % aire donde hay sensores con confianza alta o media; si no, solo suelo"],
  copa: [grad(VERDE), "Copa de árboles, de 0 % a 25 % o más"],
  personas: [grad(VERDE), "Personas: 50 % densidad del Censo y 50 % cercanía a servicios"],
};
const CAPAS_PLAN: Capa[] = [{ id: "urg", color: ["case", ["get", "k"], "#B7C298", ["==", ["get", "u"], null], "#E4DFCC", escala("u", VERDE, 0, 0.85)] }];
const CAPAS_HIST: Capa[] = [{ id: "hist", color: ["case", ["==", ["get", "hn"], null], "#E4DFCC", escala("hn", OCRE, 0, 1)] }];

function encuadreDe(anillos: number[][][], margen = 0.006): LngLatBoundsLike {
  let w = 180, s = 90, e = -180, n = -90;
  for (const a of anillos) for (const [lng, lat] of a) { w = Math.min(w, lng); e = Math.max(e, lng); s = Math.min(s, lat); n = Math.max(n, lat); }
  return [[w - margen, s - margen], [e + margen, n + margen]];
}

// Diferencia contra el promedio de Santiago; en ocre si es peor (más calor o menos copa).
function Dif({ v, base, u, bueno }: { v: number; base: number; u: string; bueno?: boolean }) {
  const d = v - base;
  if (Math.abs(d) < 0.05) return <span className="dif">igual que Santiago</span>;
  const peor = bueno ? d < 0 : d > 0;
  return <span className={`dif${peor ? " peor" : " mejor"}`}>{d > 0 ? "+" : "−"}{formato(Math.abs(d), 1)}{u}</span>;
}

function Seccion({ id, alt, children }: { id: string; alt?: boolean; children: React.ReactNode }) {
  const ref = useRevela<HTMLElement>();
  return (
    <section ref={ref} id={id} className={`b-sec b-pad revela${alt ? " alt" : ""}`}>
      <div className="b-in">{children}</div>
    </section>
  );
}

export default function Pagina({ serie }: { serie: Serie }) {
  const t = useTerreno();
  return (
    <main className="b">
      <p className="banda">Gran Santiago: 34 comunas y 13.172 cuadras. Calor de la escena Landsat más reciente, del {fechaLarga(serie.lst_fecha_ultima)}.</p>
      <header className="b-pad"><div className="b-in">
        <a className="marca" href="#inicio"><img src="/viridis.svg" alt="" width={34} height={34} />VIRIDIS</a>
        <nav aria-label="Secciones"><a href="#ahora">El calor ahora</a><a href="#planificar">Planificar</a><a href="#historico">Histórico</a><a href="#fuentes">Fuentes</a></nav>
      </div></header>

      <section className="b-hero b-pad" id="inicio">
        {/* Sentinel-2 del 6 de febrero de 2026: el oriente verde, el poniente y el sur en gris. Sin texto encima de la foto. */}
        <img className="fondo" src="/img/santiago-s2.webp" srcSet="/img/santiago-s2-1200.webp 1200w, /img/santiago-s2.webp 2400w"
          sizes="100vw" alt="" aria-hidden="true" fetchPriority="high" decoding="async" />
        <div className="velo" aria-hidden="true" />
        <div className="b-in">
          <h1>Donde se necesita <em>el verde</em></h1>
          <p>Calor del suelo, copa de árboles y personas, cuadra por cuadra, para decidir por dónde plantar el próximo corredor verde. <em>Cada metro de sombra, donde más alivia.</em></p>
          <div className="grupo" style={{ gap: 12 }}>
            <a className="pill llena grande" href="#planificar">Planificar un corredor</a>
            <a className="pill grande" href="#ahora">Ver el calor ahora</a>
          </div>
        </div>
      </section>

      {t.info && t.estado ? <Secciones {...t} info={t.info} estado={t.estado} serie={serie} /> : <Esqueletos error={t.error} />}

      <footer className="b-pad" id="fuentes"><div className="b-in">
        <h2>De dónde salen <em>los datos</em></h2>
        <p><b>Calor del suelo.</b> Landsat 8 y 9, Collection 2 Level 2 (USGS), vía Microsoft Planetary Computer. Serie mensual: {serie.escenas_landsat} escenas Landsat y {serie.escenas_sentinel2} Sentinel-2, de enero de 2023 a noviembre de 2026.</p>
        <p><b>Copa de árboles.</b> Modelo propio sobre Sentinel-2 de febrero de 2026, entrenado con la altura de copa de Meta y WRI (r = 0,92 por cuadra en comunas que el modelo no vio).</p>
        <p><b>Personas.</b> Censo 2024 del INE por manzana, más cercanía a colegios, salud, metro y paraderos de OpenStreetMap. No es ingreso.</p>
        <p><b>Aire en vivo y terreno.</b> DMC, SINCA y Sensor.Community por barrio (H3 resolución 7). Fotos y videos con GPS desde el teléfono, validados por Claude; la foto complementa al satélite, no lo reemplaza. Mapa base: CARTO y OpenStreetMap.</p>
        <p><b>Fondo del titular.</b> Sentinel-2 L2A del 6 de febrero de 2026 (Copernicus, vía Microsoft Planetary Computer), 16 m por píxel: la vegetación en verde según su NDVI y lo construido en gris.</p>
      </div></footer>
    </main>
  );
}

function Esqueletos({ error }: { error: string | null }) {
  return (
    <>
      {[["ahora", "El calor", "ahora"], ["planificar", "Planificar", "el corredor"], ["historico", "El calor", "de antes"]].map(([id, titulo, acento], k) => (
        <section key={id} id={id} className={`b-sec b-pad${k % 2 ? "" : " alt"}`} aria-busy={!error}><div className="b-in">
          <h2>{titulo} <em>{acento}</em></h2>
          {error ? (
            <p className="aviso" role="status">No hay conexión con el servidor del mapa. Desde la raíz del repo, córrelo con <code>python -m terreno.servidor --puerto 8000</code> y recarga.</p>
          ) : (
            <div className="sk-bloque" role="status" aria-label="Cargando las 34 comunas del Gran Santiago">
              <div className="sk sk-linea" style={{ width: "38%" }} />
              <div className="sk sk-mapa" />
              <div className="sk-fila"><div className="sk sk-linea" /><div className="sk sk-linea" /><div className="sk sk-linea" /></div>
            </div>
          )}
        </div></section>
      ))}
    </>
  );
}

// Polígonos de las cuadras: los arma h3-js una vez y quedan guardados.
const anillosH3 = new Map<string, number[][]>();
function anillo(h: string) {
  let a = anillosH3.get(h);
  if (!a) { const b = cellToBoundary(h, true); a = [...b, b[0]]; anillosH3.set(h, a); }
  return a;
}

type PropsSecciones = ReturnType<typeof useTerreno> & { info: InfoComunas; estado: Estado; serie: Serie };

// Lo elegido vive en la página: comunas tocadas o una zona dibujada con el lápiz (una cosa o la otra).
// El mapa siempre muestra las 34 comunas (la base) y atenúa lo que no está elegido; al servidor se le manda
// lo elegido para que Planificar trace el corredor ahí. Sin nada elegido, el área son las 34.
function Secciones(props: PropsSecciones) {
  const { info, estado, cambiar } = props;
  const [base, setBase] = useState<HexCols | null>(null);
  const completa = estado.seleccion.length === info.comunas.length && !estado.parametros.zona;
  useEffect(() => { if (completa) setBase(estado.hex); }, [completa, estado.hex]);
  const [elegidas, setElegidas] = useState<string[]>([]);
  const [zona, setZona] = useState<string[] | null>(null);
  const envio = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    clearTimeout(envio.current);
    envio.current = setTimeout(() => cambiar({ comunas: elegidas.length ? elegidas : info.comunas, distritos: [], zona }), 350);
  }, [elegidas, zona]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!base) return <Esqueletos error={props.error} />;
  return <Contenido {...props} B={base} elegidas={elegidas} setElegidas={setElegidas} zona={zona} setZona={setZona} />;
}

function Contenido({ info, estado, cambiar, ocupado, error, serie, B, elegidas, setElegidas, zona, setZona }: PropsSecciones & {
  B: HexCols; elegidas: string[]; setElegidas: React.Dispatch<React.SetStateAction<string[]>>;
  zona: string[] | null; setZona: (z: string[] | null) => void;
}) {
  const H = estado.hex;   // el área que tiene el servidor (lo elegido), para el corredor
  const nada = !elegidas.length && !zona;
  const comIdx = useMemo(() => new Map(info.comunas.map((c, i) => [c, i])), [info]);
  const idxB = useMemo(() => new Map(B.h.map((h, i) => [h, i])), [B.h]);
  const anillos = useMemo(() => B.h.map(anillo), [B.h]);
  const coleccion = (props: (i: number) => Record<string, unknown>): GeoJSON.FeatureCollection => ({
    type: "FeatureCollection",
    features: B.h.map((_, i) => ({ type: "Feature", id: i, properties: { i, c: comIdx.get(B.comuna[i]), cn: B.comuna[i], ...props(i) }, geometry: { type: "Polygon", coordinates: [anillos[i]] } })),
  });

  // Cuadras elegidas (índices de la base). null = todo Santiago.
  const zonaIdx = useMemo(() => (zona ? zona.flatMap((h) => idxB.get(h) ?? []) : []), [zona, idxB]);
  const marca = useMemo(() => {
    if (zona) return zonaIdx;
    if (!elegidas.length) return null;
    const s = new Set(elegidas);
    return B.comuna.flatMap((c, i) => (s.has(c) ? [i] : []));
  }, [zona, zonaIdx, elegidas, B.comuna]);
  const foco = useMemo<Foco>(() => (zona ? { comunas: [], hexes: zonaIdx } : elegidas.length ? { comunas: elegidas.map((c) => comIdx.get(c) ?? -1), hexes: [] } : null),
    [zona, zonaIdx, elegidas, comIdx]);
  const encuadreArea = useMemo(() => {
    if (zona && zonaIdx.length) return encuadreDe(zonaIdx.map((i) => anillos[i]), 0.004);
    const geo = elegidas.flatMap((c) => info.geo[c] ?? []).flatMap((poly) => poly.map((a) => a.map(([la, lo]) => [lo, la])));
    return encuadreDe(geo.length ? geo : anillos, 0.004);
  }, [zona, zonaIdx, elegidas, anillos, info]);

  const comunasGeo = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: info.comunas.map((c) => ({
      type: "Feature",
      properties: { c, est: elegidas.includes(c) ? "sel" : "otra" },
      geometry: { type: "MultiPolygon", coordinates: info.geo[c].map((poly) => poly.map((a) => a.map(([la, lo]) => [lo, la]))) },
    })),
  }), [info, elegidas]);
  // Sectores: el borde compartido entre dos cuadras vecinas de la misma comuna y distinto distrito.
  const distritosGeo = useMemo<GeoJSON.FeatureCollection>(() => {
    const lineas: number[][][] = [];
    B.h.forEach((h, i) => {
      for (const n of gridDisk(h, 1)) {
        const j = idxB.get(n);
        if (j == null || j <= i || B.comuna[j] !== B.comuna[i] || B.distrito[j] === B.distrito[i]) continue;
        lineas.push(directedEdgeToBoundary(cellsToDirectedEdge(h, n), true));
      }
    });
    return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: lineas } }] };
  }, [B.h, idxB]); // eslint-disable-line react-hooks/exhaustive-deps

  // Tocar una comuna la suma y tocarla otra vez la quita. Una zona dibujada se reemplaza por las comunas.
  function tocarComuna(c: string) {
    setZona(null);
    setElegidas((ant) => (ant.includes(c) ? ant.filter((x) => x !== c) : [...ant, c]));
  }
  function sumar(cs: string[]) { setZona(null); setElegidas((ant) => [...new Set([...ant, ...cs])]); }
  function reiniciar() { setZona(null); setElegidas([]); }
  // Lápiz: las cuadras que toca el contorno dibujado; cada trazo se suma a la zona anterior.
  function lazo(contorno: [number, number][]) {
    const res = getResolution(B.h[0]);
    let celdas = polygonToCellsExperimental(contorno.map(([lng, lat]) => [lat, lng]), res, POLYGON_TO_CELLS_FLAGS.containmentOverlapping).filter((h) => idxB.has(h));
    if (!celdas.length) {
      const [lng, lat] = contorno.reduce(([a, b], [x, y]) => [a + x / contorno.length, b + y / contorno.length], [0, 0]);
      celdas = [latLngToCell(lat, lng, res)].filter((h) => idxB.has(h));
    }
    if (!celdas.length) return;
    setElegidas([]);
    setZona([...new Set([...(zona ?? []), ...celdas])]);
  }

  // Suelo medio por comuna para la lista del cajón.
  const sueloComuna = useMemo(() => {
    const por: Record<string, number[]> = {};
    B.comuna.forEach((c, i) => { if (B.lst[i] != null) (por[c] ??= []).push(B.lst[i] as number); });
    return new Map(Object.entries(por).map(([c, v]) => [c, media(v)]));
  }, [B]);

  const capturasGeo = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: estado.capturas.map((c) => ({
      type: "Feature", properties: { ...c, obstaculos: (c.obstaculos ?? []).join(", "), color: c.validacion === "descartada" ? "#9A9A8E" : c.cuenta ? "#2D5E9E" : "#9A9A8E" },
      geometry: { type: "Point", coordinates: [c.lon, c.lat] },
    })),
  }), [estado.capturas]);
  const recorridosGeo = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: estado.recorridos.filter((r) => r.linea.length > 1).map((r) => ({
      type: "Feature", properties: { id: r.id }, geometry: { type: "LineString", coordinates: r.linea.map(([la, lo]) => [lo, la]) },
    })),
  }), [estado.recorridos]);
  const popupCaptura = (p: Record<string, unknown>) => {
    const c = p as unknown as Captura;
    if (c.validacion === "descartada") return `<div class="pop"><b>Descartada</b><br>${esc(c.motivo_rechazo)}</div>`;
    const cuando = new Date(String(c.tomado_en || c.medido_en)).toLocaleString("es-CL", { timeZone: "America/Santiago" });
    return `<div class="pop"><img src="/fotos/${esc(c.id)}_min.jpg" alt="Foto de terreno">
      Árboles ${Math.round(Number(c.arbol_pct ?? 0))} % (${c.fuente === "claude" ? "Claude" : "índice de verde"}) · plantable: ${esc(c.espacio_plantable ?? "sin estimar")}<br>
      ${p.obstaculos ? `Obstáculos: ${esc(p.obstaculos)}<br>` : ""}<small>${esc(c.descripcion)}</small>
      ${c.cuenta ? "" : "<br><b>Sin validar: no cuenta</b>"}<br><small>${esc(cuando)} · GPS ±${Math.round(Number(c.precision_m ?? 0))} m</small></div>`;
  };
  const mapaComun = { comunas: comunasGeo, distritos: distritosGeo, capturas: capturasGeo, recorridos: recorridosGeo, popupCaptura, alComuna: tocarComuna, alLazo: lazo, foco };

  const filtro = <FiltroComunas info={info} elegidas={elegidas} zona={zonaIdx.length} alternar={tocarComuna} sumar={sumar} reiniciar={reiniciar}
    sueloComuna={sueloComuna} ocupado={ocupado} error={error} />;

  // ---- El calor ahora (sobre las 34 comunas: la escala de color no cambia al elegir)
  const [capa, setCapa] = useState("calor");
  const [pasada, setPasada] = useState<number | null>(null);
  const calor = useMemo(() => {
    // Igual que optimizer.indice_calor: la temperatura del aire no reemplaza a la del suelo, se combina.
    const suelo = norm(B.lst), aire = norm(B.vivo);
    const conAire = new Set(B.vivo.flatMap((v, i) => (v == null ? [] : [i])));
    return suelo.map((s, i) => (s == null ? null : conAire.size && aire[i] != null ? 0.6 * s + 0.4 * (aire[i] as number) : s));
  }, [B]);
  const personas = useMemo(() => {
    const p = norm(B.pob);
    return p.map((x, i) => 0.5 * (x ?? 0.5) + 0.5 * Math.min(1, Math.max(0, B.social[i] ?? 0.5)));
  }, [B]);
  const datosAhora = useMemo(() => coleccion((i) => ({ calor: calor[i], copa: B.copa[i], personas: personas[i] })), [calor, personas, anillos]); // eslint-disable-line react-hooks/exhaustive-deps
  // Cifras de lo elegido: el total y, debajo, cada comuna (o cada comuna que toca la zona dibujada).
  const cifras = (idx: number[]) => {
    const l = sinNulos(idx.map((i) => B.lst[i])), cp = sinNulos(idx.map((i) => B.copa[i]));
    return { cuadras: idx.length, suelo: media(l), copa: media(cp), personas: idx.reduce((s, i) => s + B.pob[i], 0) };
  };
  const santiago = useMemo(() => cifras(B.h.map((_, i) => i)), [B]); // eslint-disable-line react-hooks/exhaustive-deps
  const elegido = useMemo(() => {
    if (!marca) return null;
    const por = new Map<string, number[]>();
    for (const i of marca) { const c = B.comuna[i]; if (!por.has(c)) por.set(c, []); por.get(c)!.push(i); }
    return { total: cifras(marca), filas: [...por].map(([c, idx]) => ({ c, ...cifras(idx) })).sort((a, b) => b.suelo - a.suelo) };
  }, [marca, B]); // eslint-disable-line react-hooks/exhaustive-deps
  const conAire = sinNulos((marca ?? B.h.map((_, i) => i)).map((i) => B.vivo[i]));
  const det = pasada;

  // ---- Planificar: presupuesto y pesos van al servidor, que recalcula con y sin terreno
  const p = estado.parametros;
  const [pesos, setPesos] = useState(() => {
    const tot = p.w_calor + p.w_arbol + p.w_personas || 1;
    return { km: p.km, calor: Math.round((100 * p.w_calor) / tot), arbol: Math.round((100 * p.w_arbol) / tot), pers: Math.round((100 * p.w_personas) / tot) };
  });
  const temporizador = useRef<ReturnType<typeof setTimeout>>(undefined);
  function mover(k: keyof typeof pesos, v: number) {
    const nuevo = { ...pesos, [k]: v };
    setPesos(nuevo);
    clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => {
      const w = nuevo.calor + nuevo.arbol + nuevo.pers > 0 ? nuevo : { ...nuevo, calor: 40, arbol: 40, pers: 20 };
      cambiar({ km: w.km, w_calor: w.calor, w_arbol: w.arbol, w_personas: w.pers });
    }, 450);
  }
  const total = pesos.calor + pesos.arbol + pesos.pers || 1;
  const a = estado.ahora, b = estado.antes;
  // La urgencia es relativa al área del servidor: fuera de lo elegido las cuadras quedan sin valor (gris tenue).
  const datosPlan = useMemo(() => {
    const u = new Map(H.h.map((h, j) => [h, H.u[j]]));
    return coleccion((i) => ({ u: u.get(B.h[i]) ?? null, k: B.parque[i] }));
  }, [H, anillos]); // eslint-disable-line react-hooks/exhaustive-deps
  const anillosH = useMemo(() => H.h.map(anillo), [H.h]);
  // El corredor solo se rearma si cambian sus cuadras (no cada vez que llega un estado nuevo del servidor).
  const firmaCorredor = H.h.map((h, i) => (H.ahora[i] || H.antes[i] || H.verificado[i] ? `${h}${+H.ahora[i]}${+H.antes[i]}${+H.verificado[i]}` : "")).join("");
  const corredor = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: H.h.flatMap((h, i) => [
      ...(H.ahora[i] ? ["ahora"] : []), ...(H.antes[i] ? ["antes"] : []), ...(H.verificado[i] ? ["verificado"] : []),
    ].map((tipo) => ({ type: "Feature" as const, properties: { tipo, h3: h, comuna: H.comuna[i] }, geometry: { type: "Polygon" as const, coordinates: [anillosH[i]] } }))),
  }), [firmaCorredor, anillosH]); // eslint-disable-line react-hooks/exhaustive-deps
  const enCorredor = H.h.flatMap((_, i) => (H.ahora[i] ? [i] : []));
  const comunasCorredor = [...new Set(enCorredor.map((i) => H.comuna[i]))].sort();
  const claveCorredor = enCorredor.map((i) => H.h[i]).join();
  // Por defecto se ve el área completa (las 34 comunas si están todas); el corredor se acerca a pedido.
  const [cerca, setCerca] = useState(false);
  useEffect(() => setCerca(false), [encuadreArea]);
  const encuadrePlan = useMemo(() => (cerca && enCorredor.length ? encuadreDe(enCorredor.map((i) => anillosH[i]), 0.025) : encuadreArea),
    [cerca, claveCorredor, encuadreArea]); // eslint-disable-line react-hooks/exhaustive-deps

  function exportar() {
    const fc = { type: "FeatureCollection", features: corredor.features.filter((f) => f.properties?.tipo === "ahora") };
    const blob = new Blob([JSON.stringify(fc)], { type: "application/geo+json" });
    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(blob);
    enlace.download = `corredor_${formato(a.km, 2).replace(",", "_")}km.geojson`;
    enlace.click();
    URL.revokeObjectURL(enlace.href);
  }

  // ---- Histórico: el servidor promedia las escenas del área entre dos fechas
  const [refHist, verHist] = useVisible<HTMLDivElement>("300px");
  const [desde, setDesde] = useState(12);
  const [hist, setHist] = useState<Map<string, number> | null>(null);
  const [mesesHist, setMesesHist] = useState(0);
  const [errHist, setErrHist] = useState<string | null>(null);
  const hasta = `${serie.meses[serie.meses.length - 1]}-28`;
  useEffect(() => {
    if (!verHist) return;
    let vivo = true;
    historico(`${serie.meses[desde]}-01`, hasta)
      .then((r) => { if (vivo) { setHist(new Map(r.h.flatMap((h, i) => (r.lst[i] == null ? [] : [[h, r.lst[i] as number] as const])))); setMesesHist(r.meses); setErrHist(null); } })
      .catch((e) => vivo && setErrHist(String(e.message)));
    return () => { vivo = false; };
  }, [verHist, desde, estado.sel_id, hasta, serie.meses]);
  const promHex = useMemo(() => B.h.map((h) => hist?.get(h) ?? null), [hist, B.h]);
  const escalaHist = useMemo(() => {
    const v = sinNulos(promHex).sort((x, y) => x - y);
    return v.length ? [v[Math.floor(v.length * 0.02)], v[Math.ceil(v.length * 0.98) - 1]] : [0, 1];
  }, [promHex]);
  const datosHist = useMemo(() => coleccion((i) => ({
    hn: promHex[i] == null ? null : Math.min(1, Math.max(0, ((promHex[i] as number) - escalaHist[0]) / (escalaHist[1] - escalaHist[0] || 1))),
  })), [promHex, escalaHist, anillos]); // eslint-disable-line react-hooks/exhaustive-deps
  const histComuna = useMemo(() => {
    const por: Record<string, number[]> = {};
    (marca ?? B.h.map((_, i) => i)).forEach((i) => { if (promHex[i] != null) (por[B.comuna[i]] ??= []).push(promHex[i] as number); });
    return Object.entries(por).map(([c, v]) => [c, media(v)] as const).sort((x, y) => y[1] - x[1]);
  }, [promHex, B, marca]);
  const promElegido = media(sinNulos((marca ?? B.h.map((_, i) => i)).map((i) => promHex[i])));
  const mm = sinNulos(serie.media_mes);
  const lo = Math.min(...mm), hi = Math.max(...mm);

  return (
    <>
      <Seccion id="ahora" alt>
        <div className="b-cab escalon">
          <h2>El calor <em>ahora</em></h2>
          <div className="grupo" role="group" aria-label="Capa del mapa">
            {CAPAS_AHORA.map((c) => <button key={c.id} type="button" className="pill" aria-pressed={capa === c.id} onClick={() => setCapa(c.id)}>{NOMBRE_CAPA[c.id]}</button>)}
          </div>
        </div>
        <div className="escalon" style={est(1)}>
          <MapaHex {...mapaComun} datos={datosAhora} capas={CAPAS_AHORA} activa={capa} encuadre={encuadreArea} alPasar={setPasada}
            etiqueta={`Mapa de ${NOMBRE_CAPA[capa].toLowerCase()} por cuadra. Toca una comuna para sumarla o quitarla.`}>{filtro}</MapaHex>
        </div>
        <div className="leyenda">
          <span><i className="barra" style={{ background: LEYENDA[capa][0] }} />{LEYENDA[capa][1]}</span>
          <span><i className="linea" style={{ borderTop: "2px solid #2F4520" }} />Comuna</span>
          <span><i className="linea" style={{ borderTop: "2px dashed #2F4520", opacity: 0.7 }} />Sector</span>
          {!nada && <span><i className="cuadro" style={{ background: "#C5CDA6", opacity: 0.35 }} />Fuera de lo elegido</span>}
          <span className="detalle num" aria-live="polite">{det != null
            ? `${B.distrito[det]}${B.parque[det] ? ", parque" : ""}: suelo ${formato(B.lst[det] ?? 0, 1)} °C${B.vivo[det] != null ? `, aire ${formato(B.vivo[det] as number, 1)} °C` : ""}, copa ${formato(B.copa[det] ?? 0, 1)} %, ${formato(B.pob[det])} personas.`
            : "Pasa el puntero por una cuadra para ver sus datos."}</span>
        </div>
        <div className="elegido escalon" style={est(3)}>
          {!elegido ? (
            <p className="vacio">Todo Santiago: <b className="num">{formato(santiago.suelo, 1)} °C</b> de suelo, <b className="num">{formato(santiago.copa, 1)} %</b> de copa y <b className="num">{formato(santiago.personas)}</b> personas en {formato(santiago.cuadras)} cuadras. Toca comunas en el mapa o encierra cuadras con el lápiz para ver aquí sus cifras.</p>
          ) : (
            <>
              <div className="totales num">
                <span className="quien">{zona ? "Zona dibujada" : elegidas.length === 1 ? elegidas[0] : `${elegidas.length} comunas`}</span>
                <span><b><Cifra valor={elegido.total.suelo} dec={1} /> °C</b> suelo <Dif v={elegido.total.suelo} base={santiago.suelo} u=" °C" /></span>
                <span><b><Cifra valor={elegido.total.copa} dec={1} /> %</b> copa <Dif v={elegido.total.copa} base={santiago.copa} u=" pts" bueno /></span>
                <span><b><Cifra valor={elegido.total.personas} /></b> personas</span>
                <span><b>{formato(elegido.total.cuadras)}</b> cuadras</span>
              </div>
              {(elegido.filas.length > 1 || zona) && (
                <div className="tabla-env">
                  <table className="tabla-elegido num">
                    <thead><tr><th scope="col">{zona ? "Comunas que toca la zona" : "Comuna"}</th><th scope="col">Suelo</th><th scope="col">Frente a Santiago</th><th scope="col">Copa</th><th scope="col">Personas</th><th scope="col">Cuadras</th>{!zona && <th scope="col"><span className="sr">Quitar</span></th>}</tr></thead>
                    <tbody>
                      {elegido.filas.map((f) => (
                        <tr key={f.c}>
                          <th scope="row">{f.c}</th>
                          <td>{formato(f.suelo, 1)} °C</td>
                          <td><Dif v={f.suelo} base={santiago.suelo} u=" °C" /></td>
                          <td>{formato(f.copa, 1)} %</td>
                          <td>{formato(f.personas)}</td>
                          <td>{formato(f.cuadras)}</td>
                          {!zona && <td><button type="button" className="quita" aria-label={`Quitar ${f.c}`} onClick={() => tocarComuna(f.c)}>×</button></td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="nota">Santiago completo: {formato(santiago.suelo, 1)} °C de suelo y {formato(santiago.copa, 1)} % de copa. {conAire.length
                ? `Aire en vivo con confianza alta o media en ${conAire.length.toLocaleString("es-CL")} cuadras de lo elegido: ${formato(media(conAire), 1)} °C de media.`
                : "Sin sensores de aire con confianza alta o media en lo elegido: el calor sale solo del satélite."}</p>
            </>
          )}
        </div>
      </Seccion>

      <Seccion id="planificar">
        <div className="b-cab escalon"><h2>Planificar <em>el corredor</em></h2><p>Mueve los pesos y el presupuesto; el corredor se traza de parque a parque por las cuadras más urgentes del área elegida.</p></div>
        <div className="b-controles escalon" style={est(2)}>
          {([["calor", "Calor (suelo y aire)"], ["arbol", "Falta de árboles"], ["pers", "Personas cerca"]] as const).map(([k, nombre]) => (
            <div className="peso" key={k}>
              <label htmlFor={`p-${k}`}><span>{nombre}</span><b>{Math.round((100 * pesos[k]) / total)} %</b></label>
              <input id={`p-${k}`} type="range" min={0} max={100} step={5} value={pesos[k]} onChange={(e) => mover(k, Number(e.target.value))} />
            </div>
          ))}
          <div className="peso">
            <label htmlFor="p-km"><span>Presupuesto</span><b>{formato(pesos.km, pesos.km % 1 ? 1 : 0)} km</b></label>
            <input id="p-km" type="range" min={1} max={20} step={0.5} value={pesos.km} onChange={(e) => mover("km", Number(e.target.value))} />
          </div>
        </div>
        <div className="b-plan">
          <div className="izq escalon" style={est(3)}>
            <MapaHex {...mapaComun} datos={datosPlan} capas={CAPAS_PLAN} activa="urg" corredor={corredor} encuadre={encuadrePlan}
              etiqueta="Corredor propuesto sobre la urgencia de cada cuadra">{filtro}</MapaHex>
            {enCorredor.length > 0 && (
              <button type="button" className="pill zoom-corredor" aria-pressed={cerca} onClick={() => setCerca(!cerca)}>
                {cerca ? (nada ? "Ver las 34 comunas" : "Ver toda el área") : "Acercar al corredor"}
              </button>
            )}
            <div className="leyenda">
              <span><i className="barra" style={{ background: grad(VERDE) }} />Urgencia</span>
              <span><i className="cuadro" style={{ background: "#22301A" }} />Corredor</span>
              <span><i className="cuadro" style={{ background: "#B7C298" }} />Parque</span>
              <span><i className="linea" style={{ borderTop: "2px dashed #22281A" }} />Sin datos de terreno</span>
              <span><i className="linea" style={{ borderTop: "3px solid #B0398B" }} />Verificado en terreno</span>
              <span><i className="cuadro" style={{ background: "#2D5E9E", borderRadius: 7 }} />Foto válida</span>
            </div>
          </div>
          <div className="cifras">
            {a.hexes ? (
              <>
                <div className="cifra escalon" style={est(4)}>
                  <b><Cifra valor={a.personas_cubiertas} /></b>
                  <span>personas viven junto al corredor. Con un trazado al azar del mismo largo serían <strong className="num"><Cifra valor={a.personas_azar} /></strong>.</span>
                </div>
                <div className="cifra escalon" style={est(5)}>
                  <b><Cifra valor={a.km} dec={2} sufijo={" km"} /></b>
                  <span>en {a.hexes} cuadras{comunasCorredor.length ? `, en ${comunasCorredor.join(", ")}` : ""}. Urgencia cubierta {formato(a.urgencia_cubierta, 3)}, contra {formato(a.urgencia_azar, 3)} al azar.</span>
                </div>
              </>
            ) : <p className="aviso">Sin corredor: el área no tiene un parque consolidado desde donde partir. Suma una comuna vecina.</p>}
            <table className="terreno num">
              <caption>Efecto de la captura en terreno</caption>
              <thead><tr><th /><th>Sin terreno</th><th>Con terreno</th></tr></thead>
              <tbody>
                <tr><th>Urgencia cubierta</th><td>{formato(b.urgencia_cubierta, 3)}</td><td>{formato(a.urgencia_cubierta, 3)}</td></tr>
                <tr><th>Personas</th><td>{formato(b.personas_cubiertas)}</td><td>{formato(a.personas_cubiertas)}</td></tr>
                <tr><th>Largo</th><td>{formato(b.km, 2)} km</td><td>{formato(a.km, 2)} km</td></tr>
                <tr><th>Verificadas</th><td>{b.verificados}</td><td>{a.verificados}</td></tr>
              </tbody>
            </table>
            <div className="grupo escalon" style={est(6)}>
              <button type="button" className="pill llena" onClick={exportar} disabled={!a.hexes}>Exportar tramos</button>
            </div>
            <p className="nota">{estado.capturas.length} {estado.capturas.length === 1 ? "captura" : "capturas"} en terreno; {estado.capturas.filter((c) => c.cuenta).length} cuentan. El mapa se actualiza solo cuando llega una foto nueva.</p>
          </div>
        </div>
      </Seccion>

      <Seccion id="historico" alt>
        <div className="b-cab escalon"><h2>El calor <em>de antes</em></h2><p>Elige desde qué mes promediar el calor del suelo del área: {serie.escenas_landsat} escenas Landsat, de enero de 2023 a noviembre de 2026.</p></div>
        <div ref={refHist} className="escalon" style={{ ...est(1), display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="b-meses" role="group" aria-label="Mes desde el que se promedia">
            {serie.meses.map((m, j) => {
              const v = serie.media_mes[j];
              const alto = v == null ? 8 : 14 + (86 * (v - lo)) / (hi - lo || 1);
              return (
                <button key={m} type="button" aria-pressed={j === desde} onClick={() => setDesde(j)}
                  aria-label={`${mesCorto(m)}${v != null ? `, suelo medio ${formato(v, 1)} °C` : ", sin escena Landsat"}`}
                  title={`${mesCorto(m)}${v != null ? ` · ${formato(v, 1)} °C` : " · sin escena"}`}>
                  <span style={{ height: `${alto}%`, background: j < desde ? "#D6D9BF" : esVerano(m) ? "#4F6E31" : "#8C9A63", outline: j === desde ? "2px solid #22281A" : undefined, outlineOffset: 1 }} />
                </button>
              );
            })}
          </div>
          <div className="b-ejes num"><span>ene 2023</span><span>ene 2024</span><span>ene 2025</span><span>ene 2026</span><span>nov 2026</span></div>
        </div>
        <div className="b-hist">
          <div className="izq escalon" style={est(2)}>
            <MapaHex {...mapaComun} datos={datosHist} capas={CAPAS_HIST} activa="hist" encuadre={encuadreArea} etiqueta="Promedio del calor del suelo por cuadra en el rango elegido">{filtro}</MapaHex>
            <div className="leyenda" style={{ marginTop: 10 }}><span><i className="barra" style={{ background: grad(OCRE) }} />{hist ? <span className="num">Suelo medio de {formato(escalaHist[0], 1)} °C a {formato(escalaHist[1], 1)} °C</span> : <span className="sk sk-linea" style={{ display: "inline-block", width: 190, height: 14 }} aria-label="Calculando el promedio" />}</span></div>
          </div>
          <div className="cifras">
            <p style={{ margin: 0, fontSize: 16, color: "var(--oliva-osc)" }}>Rango elegido: <b>{mesCorto(serie.meses[desde])} a nov 2026</b>, {mesesHist} meses con escenas. Las barras altas son los veranos, que son los que usa el índice de calor.</p>
            {errHist && <p className="aviso" role="alert">{errHist}</p>}
            <div className="cifra escalon" style={est(3)}>
              <b>{hist ? <Cifra valor={promElegido} dec={1} sufijo={" °C"} duracion={700} /> : "…"}</b>
              <span>suelo medio del área en el rango.</span>
            </div>
            {histComuna.length > 1 && (
              <p className="nota" style={{ fontSize: 15 }}>Más calientes en el rango: {histComuna.slice(0, 3).map(([c, v]) => `${c} (${formato(v, 1)} °C)`).join(", ")}. Más fresca: {histComuna[histComuna.length - 1][0]} ({formato(histComuna[histComuna.length - 1][1], 1)} °C).</p>
            )}
          </div>
        </div>
      </Seccion>
    </>
  );
}
