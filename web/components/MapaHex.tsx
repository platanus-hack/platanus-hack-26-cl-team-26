"use client";
import { useEffect, useRef, useState } from "react";
import type { ExpressionSpecification, GeoJSONSource, LngLatBoundsLike, Map as MapaML, Popup } from "maplibre-gl";
import { menosMovimiento, useVisible } from "./movimiento";

// Mapa base: Carto Positron teñido con la paleta crema y salvia. Encima, en este orden:
// hexágonos (una capa de relleno por vista; al cambiar de vista se cruzan las opacidades),
// contornos de comuna (del servidor de terreno; se tocan para elegir el área), corredor
// (relleno del actual, línea punteada del de sin terreno, magenta donde se verificó en terreno),
// y capturas en terreno con sus recorridos.
const ESTILO = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const OPACIDAD = 0.82;
const VACIO: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export type Capa = { id: string; color: ExpressionSpecification };

function tenir(mapa: MapaML) {
  for (const l of mapa.getStyle().layers ?? []) {
    const id = l.id.toLowerCase();
    try {
      if (l.type === "background") mapa.setPaintProperty(l.id, "background-color", "#EFE9DA");
      else if (l.type === "fill" && id.includes("water")) mapa.setPaintProperty(l.id, "fill-color", "#CDD6C2");
      else if (l.type === "fill" && /park|wood|grass|forest/.test(id)) mapa.setPaintProperty(l.id, "fill-color", "#DCE0C4");
      else if (l.type === "fill" && /landcover|landuse/.test(id)) mapa.setPaintProperty(l.id, "fill-color", "#EAE5D3");
      else if (l.type === "fill" && id.includes("building")) mapa.setPaintProperty(l.id, "fill-color", "#E6DFCB");
      else if (l.type === "line" && /road|bridge|tunnel|highway|street/.test(id)) mapa.setPaintProperty(l.id, "line-color", "#FBF8EF");
      else if (l.type === "line" && id.includes("water")) mapa.setPaintProperty(l.id, "line-color", "#CDD6C2");
      else if (l.type === "symbol") {
        if (/poi|housenum/.test(id)) mapa.setLayoutProperty(l.id, "visibility", "none");
        else mapa.setPaintProperty(l.id, "text-color", "#59623F");
      }
    } catch { /* capa sin esa propiedad */ }
  }
}

export default function MapaHex({ datos, capas, activa, corredor, comunas, capturas, recorridos, popupCaptura,
  encuadre, alElegir, alComuna, etiqueta }: {
  datos: GeoJSON.FeatureCollection;
  capas: Capa[];
  activa: string;
  corredor?: GeoJSON.FeatureCollection;      // polígonos con propiedad tipo: "ahora" | "antes" | "verificado"
  comunas?: GeoJSON.FeatureCollection;       // contornos con propiedades c (nombre) y est: todas | sel | vec | otra
  capturas?: GeoJSON.FeatureCollection;      // puntos con propiedad color
  recorridos?: GeoJSON.FeatureCollection;
  popupCaptura?: (props: Record<string, unknown>) => string;
  encuadre: LngLatBoundsLike;
  alElegir?: (i: number | null) => void;
  alComuna?: (c: string) => void;
  etiqueta: string;
}) {
  const [cont, visible] = useVisible<HTMLDivElement>();
  const nodo = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapaML | null>(null);
  const [listo, setListo] = useState(false);
  const elegido = useRef<number | null>(null);
  const cb = useRef({ alElegir, alComuna, popupCaptura, activa });
  cb.current = { alElegir, alComuna, popupCaptura, activa };
  const inicial = useRef({ datos, capas, activa, encuadre });

  useEffect(() => {
    if (!visible || !nodo.current) return;
    let vivo = true;
    let m: MapaML | null = null;
    let popup: Popup | null = null;
    import("maplibre-gl").then((ml) => {
      if (!vivo || !nodo.current) return;
      // El worker de MapLibre 6 se sirve desde public/ (lo copia "npm run worker").
      ml.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      const ini = inicial.current;
      const nuevo = new ml.Map({
        container: nodo.current, style: ESTILO, bounds: ini.encuadre,
        fitBoundsOptions: { padding: 32 }, attributionControl: { compact: true },
        cooperativeGestures: true, dragRotate: false, pitchWithRotate: false,
        locale: {
          "CooperativeGesturesHandler.WindowsHelpText": "Usa Ctrl + rueda para acercar el mapa",
          "CooperativeGesturesHandler.MacHelpText": "Usa ⌘ + rueda para acercar el mapa",
          "CooperativeGesturesHandler.MobileHelpText": "Usa dos dedos para mover el mapa",
          "NavigationControl.ZoomIn": "Acercar", "NavigationControl.ZoomOut": "Alejar",
        },
      });
      m = nuevo;
      nuevo.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
      nuevo.on("load", () => {
        tenir(nuevo);
        const fundido = { duration: menosMovimiento() ? 0 : 650 };
        nuevo.addSource("hex", { type: "geojson", data: ini.datos, promoteId: "i" });
        for (const c of ini.capas) {
          nuevo.addLayer({
            id: c.id, type: "fill", source: "hex",
            paint: { "fill-color": c.color, "fill-opacity": c.id === ini.activa ? OPACIDAD : 0, "fill-opacity-transition": fundido },
          });
        }
        nuevo.addLayer({
          id: "borde", type: "line", source: "hex",
          paint: {
            "line-color": ["case", ["boolean", ["feature-state", "sel"], false], "#22281A", "#F6F1E4"],
            "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 2.6, 0.35],
          },
        });
        nuevo.addSource("comunas", { type: "geojson", data: VACIO });
        nuevo.addLayer({
          id: "comunas-relleno", type: "fill", source: "comunas",
          paint: { "fill-color": "#4F6E31", "fill-opacity": ["match", ["get", "est"], "vec", 0.1, "otra", 0.05, 0.001] },
        });
        nuevo.addLayer({
          id: "comunas-linea", type: "line", source: "comunas", filter: ["!=", ["get", "est"], "vec"],
          paint: {
            "line-color": ["match", ["get", "est"], "otra", "#8C9A63", "#2F4520"],
            "line-width": ["match", ["get", "est"], "sel", 2.6, "todas", 0.9, 1],
          },
        });
        nuevo.addLayer({
          id: "comunas-vecina", type: "line", source: "comunas", filter: ["==", ["get", "est"], "vec"],
          paint: { "line-color": "#2F4520", "line-width": 1.8, "line-dasharray": [3, 3] },
        });
        nuevo.addSource("corredor", { type: "geojson", data: VACIO });
        nuevo.addLayer({
          id: "corredor", type: "fill", source: "corredor", filter: ["==", ["get", "tipo"], "ahora"],
          paint: { "fill-color": "#22301A", "fill-opacity": 0.92, "fill-opacity-transition": { duration: menosMovimiento() ? 0 : 700 } },
        });
        // Contorno grueso para que el corredor se distinga aun con el área completa a la vista.
        nuevo.addLayer({
          id: "corredor-borde", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "ahora"],
          paint: { "line-color": "#22301A", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3, 13, 1] },
        });
        nuevo.addLayer({
          id: "corredor-antes", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "antes"],
          paint: { "line-color": "#22281A", "line-width": 1.6, "line-dasharray": [2, 2] },
        });
        nuevo.addLayer({
          id: "corredor-verificado", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "verificado"],
          paint: { "line-color": "#B0398B", "line-width": 3 },
        });
        nuevo.addSource("recorridos", { type: "geojson", data: VACIO });
        nuevo.addLayer({ id: "recorridos", type: "line", source: "recorridos", paint: { "line-color": "#6B3FA0", "line-width": 4, "line-opacity": 0.85 } });
        nuevo.addSource("capturas", { type: "geojson", data: VACIO });
        nuevo.addLayer({
          id: "capturas", type: "circle", source: "capturas",
          paint: { "circle-radius": 7, "circle-color": ["get", "color"], "circle-stroke-color": "#FFFDF6", "circle-stroke-width": 2 },
        });

        // Un toque: captura → su foto; cuadra del área → su detalle; otra comuna → elegirla.
        nuevo.on("click", (e) => {
          const cap = nuevo.queryRenderedFeatures(e.point, { layers: ["capturas"] })[0];
          if (cap && cb.current.popupCaptura) {
            popup?.remove();
            popup = new ml.Popup({ maxWidth: "260px" }).setLngLat(e.lngLat).setHTML(cb.current.popupCaptura(cap.properties)).addTo(nuevo);
            return;
          }
          const hex = nuevo.getLayer(cb.current.activa) ? nuevo.queryRenderedFeatures(e.point, { layers: [cb.current.activa] })[0] : undefined;
          if (hex) {
            const i = Number(hex.id);
            if (elegido.current != null) nuevo.setFeatureState({ source: "hex", id: elegido.current }, { sel: false });
            elegido.current = i === elegido.current ? null : i;
            if (elegido.current != null) nuevo.setFeatureState({ source: "hex", id: elegido.current }, { sel: true });
            cb.current.alElegir?.(elegido.current);
            return;
          }
          const com = nuevo.queryRenderedFeatures(e.point, { layers: ["comunas-relleno"] })[0];
          if (com) cb.current.alComuna?.(String(com.properties.c));
        });
        nuevo.on("mousemove", (e) => {
          const capas = ["capturas", "comunas-relleno", cb.current.activa].filter((x) => nuevo.getLayer(x));
          nuevo.getCanvas().style.cursor = nuevo.queryRenderedFeatures(e.point, { layers: capas }).length ? "pointer" : "";
        });
        setListo(true);
      });
      mapa.current = nuevo;
    });
    return () => { vivo = false; popup?.remove(); m?.remove(); mapa.current = null; setListo(false); };
  }, [visible]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    for (const c of capas) if (m.getLayer(c.id)) m.setPaintProperty(c.id, "fill-opacity", c.id === activa ? OPACIDAD : 0);
  }, [activa, capas, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    if (elegido.current != null) { m.removeFeatureState({ source: "hex" }); elegido.current = null; }
    (m.getSource("hex") as GeoJSONSource).setData(datos);
  }, [datos, listo]);

  useEffect(() => {
    if (listo) (mapa.current?.getSource("comunas") as GeoJSONSource | undefined)?.setData(comunas ?? VACIO);
  }, [comunas, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    (m.getSource("capturas") as GeoJSONSource).setData(capturas ?? VACIO);
    (m.getSource("recorridos") as GeoJSONSource).setData(recorridos ?? VACIO);
  }, [capturas, recorridos, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m || !corredor) return;
    // El corredor nuevo aparece desde transparente.
    (m.getSource("corredor") as GeoJSONSource).setData(corredor);
    if (menosMovimiento()) return;
    m.setPaintProperty("corredor", "fill-opacity", 0);
    const t = setTimeout(() => m.getLayer("corredor") && m.setPaintProperty("corredor", "fill-opacity", 0.92), 60);
    return () => clearTimeout(t);
  }, [corredor, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    m.fitBounds(encuadre, { padding: 32, duration: menosMovimiento() ? 0 : 1400, essential: false });
  }, [encuadre, listo]);

  return (
    <div ref={cont} className="mapa" role="region" aria-label={etiqueta}>
      <div ref={nodo} style={{ position: "absolute", inset: 0 }} />
      {!listo && <div className="mapa-carga" aria-hidden="true">Cargando mapa…</div>}
    </div>
  );
}
