"use client";
import { useEffect, useRef, useState } from "react";
import type { ExpressionSpecification, GeoJSONSource, LngLatBoundsLike, Map as MapaML, MapGeoJSONFeature, MapMouseEvent } from "maplibre-gl";
import { menosMovimiento, useVisible } from "./movimiento";

// Mapa base: el mismo Carto Positron que usa app.py (pydeck, map_style "carto-positron"),
// teñido con la paleta crema y salvia. Encima, una capa de relleno por cada vista; al cambiar
// de vista se cruzan las opacidades, así la transición es suave.
const ESTILO = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const OPACIDAD = 0.82;

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

export default function MapaHex({ datos, capas, activa, corredor, encuadre, alElegir, etiqueta }: {
  datos: GeoJSON.FeatureCollection;
  capas: Capa[];
  activa: string;
  corredor?: GeoJSON.FeatureCollection;
  encuadre: LngLatBoundsLike;
  alElegir?: (i: number | null) => void;
  etiqueta: string;
}) {
  const [cont, visible] = useVisible<HTMLDivElement>();
  const nodo = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapaML | null>(null);
  const [listo, setListo] = useState(false);
  const elegido = useRef<number | null>(null);
  const cb = useRef(alElegir);
  cb.current = alElegir;
  const inicial = useRef({ datos, capas, activa, corredor, encuadre });

  useEffect(() => {
    if (!visible || !nodo.current) return;
    let vivo = true;
    let m: MapaML | null = null;
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
      m.on("load", () => {
        if (!m) return;
        tenir(m);
        m.addSource("hex", { type: "geojson", data: ini.datos, promoteId: "i" });
        for (const c of ini.capas) {
          m.addLayer({
            id: c.id, type: "fill", source: "hex",
            paint: { "fill-color": c.color, "fill-opacity": c.id === ini.activa ? OPACIDAD : 0, "fill-opacity-transition": { duration: menosMovimiento() ? 0 : 650 } },
          });
        }
        m.addLayer({
          id: "borde", type: "line", source: "hex",
          paint: {
            "line-color": ["case", ["boolean", ["feature-state", "sel"], false], "#22281A", "#F6F1E4"],
            "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 2.6, 0.6],
          },
        });
        m.addSource("corredor", { type: "geojson", data: ini.corredor ?? { type: "FeatureCollection", features: [] } });
        m.addLayer({
          id: "corredor", type: "fill", source: "corredor",
          paint: { "fill-color": "#22301A", "fill-opacity": 0.92, "fill-opacity-transition": { duration: menosMovimiento() ? 0 : 700 } },
        });
        m.addLayer({ id: "corredor-borde", type: "line", source: "corredor", paint: { "line-color": "#EFE9DA", "line-width": 1 } });
        const pick = (e: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
          const f = e.features?.[0];
          const i = f ? Number(f.id) : null;
          if (elegido.current != null) m!.setFeatureState({ source: "hex", id: elegido.current }, { sel: false });
          elegido.current = i === elegido.current ? null : i;
          if (elegido.current != null) m!.setFeatureState({ source: "hex", id: elegido.current }, { sel: true });
          cb.current?.(elegido.current);
        };
        for (const c of ini.capas) {
          m.on("click", c.id, pick);
          m.on("mouseenter", c.id, () => { m!.getCanvas().style.cursor = "pointer"; });
          m.on("mouseleave", c.id, () => { m!.getCanvas().style.cursor = ""; });
        }
        setListo(true);
      });
      mapa.current = m;
    });
    return () => { vivo = false; m?.remove(); mapa.current = null; setListo(false); };
  }, [visible]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    for (const c of capas) if (m.getLayer(c.id)) m.setPaintProperty(c.id, "fill-opacity", c.id === activa ? OPACIDAD : 0);
  }, [activa, capas, listo]);

  useEffect(() => {
    if (listo) (mapa.current?.getSource("hex") as GeoJSONSource | undefined)?.setData(datos);
  }, [datos, listo]);

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
