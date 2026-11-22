import { readFileSync } from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import { Fragment } from "react";

import { VulnerabilidadMetodo } from "./vulnerabilidad";

// Todas las fuentes de datos de Viridis, ordenadas por tema: qué es cada una, para qué se usa y su sitio oficial.
// El pie de la página principal resume lo mismo y enlaza aquí.
export const metadata: Metadata = {
  title: "Fuentes · Viridis",
  description: "De dónde salen los datos de Viridis: satélites, censo, estaciones meteorológicas, registros de aves y abejas, y mapas base.",
};

type Fuente = { nombre: string; quien: string; uso: string; url: string; enlace: string };
const TEMAS: { id: string; titulo: string; acento: string; nota?: string; mas?: [string, string]; fuentes: Fuente[] }[] = [
  {
    id: "calor", titulo: "Calor", acento: "del suelo",
    nota: "El mapa y el índice usan la escena de verano del 19 de febrero de 2026. El histórico usa la serie mensual: {landsat} escenas Landsat y {sentinel} Sentinel-2, de enero de 2023 a noviembre de 2026.",
    fuentes: [
      { nombre: "Landsat 8 y 9, Collection 2 Level 2", quien: "USGS y NASA",
        uso: "Temperatura de la superficie a 30 m (banda térmica a 100 m). Es el calor de cada cuadra y la serie del histórico.",
        url: "https://www.usgs.gov/landsat-missions/landsat-collection-2-level-2-science-products", enlace: "usgs.gov" },
      { nombre: "Planetary Computer", quien: "Microsoft",
        uso: "Catálogo desde donde se descargan las escenas Landsat y Sentinel-2 ya corregidas.",
        url: "https://planetarycomputer.microsoft.com/", enlace: "planetarycomputer.microsoft.com" },
    ],
  },
  {
    id: "arboles", titulo: "Árboles", acento: "y vegetación",
    nota: "El modelo de copa es propio, sobre Sentinel-2 de febrero de 2026: sigue al mapa de Meta con correlación 0,92 por cuadra en comunas que no vio al entrenar. El fondo del titular es la misma imagen del 6 de febrero de 2026 a 16 m por píxel, con la vegetación en verde según su NDVI y lo construido en gris.",
    fuentes: [
      { nombre: "Sentinel-2 L2A", quien: "ESA · Copernicus",
        uso: "Imagen de 10 m del 6 de febrero de 2026: entrada del modelo de copa, índice de vegetación (NDVI) y fondo del titular.",
        url: "https://dataspace.copernicus.eu/", enlace: "dataspace.copernicus.eu" },
      { nombre: "Mapa global de altura de copa (1 m)", quien: "Meta y World Resources Institute · Tolan et al. 2024",
        uso: "Respuesta correcta con que se entrenó y validó el modelo de copa de árboles.",
        url: "https://doi.org/10.1016/j.rse.2023.113888", enlace: "Remote Sensing of Environment 300" },
      { nombre: "WorldCover 2021", quien: "ESA",
        uso: "Cobertura de suelo a 10 m: pasto y construido, y la comparación contra nuestro modelo.",
        url: "https://esa-worldcover.org/", enlace: "esa-worldcover.org" },
    ],
  },
  {
    id: "personas", titulo: "Personas", acento: "y servicios",
    nota: "La capa de personas es 70 % habitantes de la cuadra y 30 % cercanía a colegios, salud, metro y paraderos. La vulnerabilidad al calor promedia la sensibilidad (personas de 60 años o más, de 0 a 5 años y con discapacidad) y la capacidad de adaptarse (viviendas hacinadas e irrecuperables y años de escolaridad), cada parte normalizada sobre las 34 comunas; entra solo en la urgencia de las personas, con 10 % por omisión. Ninguna es ingreso: el Censo no lo pregunta.",
    mas: ["#vulnerabilidad", "Cómo se calcula la vulnerabilidad al calor ↓"],
    fuentes: [
      { nombre: "Censo de Población y Vivienda 2024", quien: "Instituto Nacional de Estadísticas (INE)",
        uso: "Habitantes por manzana y, para la vulnerabilidad al calor, edades, discapacidad, viviendas hacinadas e irrecuperables y escolaridad, repartidos a cada cuadra según el área que comparten.",
        url: "https://censo2024.ine.gob.cl/", enlace: "censo2024.ine.gob.cl" },
      { nombre: "OpenStreetMap", quien: "Colaboradores de OpenStreetMap · extracto de Geofabrik",
        uso: "Parques y cerros isla, colegios, centros de salud, metro y paraderos; y los nombres de autopistas y avenidas del mapa.",
        url: "https://www.openstreetmap.org/copyright", enlace: "openstreetmap.org" },
    ],
  },
  {
    id: "aire", titulo: "Aire", acento: "máxima del día",
    nota: "Cada noche se calcula la temperatura máxima del día anterior de cada estación oficial y se reparte por barrio (H3 resolución 7) con distancia inversa. Una estación cuenta solo si midió en al menos 3 de las 4 horas más calientes (14 a 18 h). El aire entra al índice de calor solo donde hay al menos 5 barrios con confianza alta o media, y pesa 30 % frente al suelo.",
    fuentes: [
      { nombre: "Red de estaciones automáticas", quien: "Dirección Meteorológica de Chile (DMC)",
        uso: "Temperatura y humedad minuto a minuto de las estaciones de Santiago; de ahí sale la máxima del día.",
        url: "https://climatologia.meteochile.gob.cl/", enlace: "climatologia.meteochile.gob.cl" },
      { nombre: "SINCA", quien: "Ministerio del Medio Ambiente",
        uso: "Temperatura y humedad horarias de 9 estaciones oficiales de Santiago; se suman a las de la DMC.",
        url: "https://sinca.mma.gob.cl/", enlace: "sinca.mma.gob.cl" },
    ],
  },
  {
    id: "fauna", titulo: "Aves", acento: "y abejas",
    nota: "Registros con coordenadas desde 2015, contados por barrio porque muchas ubicaciones tienen un margen de cientos de metros (las abejas con más de 1 km se descartan). La abeja de miel y el abejorro europeo van aparte, por exóticos. Un registro dice que alguien vio la especie ahí: no haber registro no significa que no esté, y hay más observadores en parques y cerros.",
    fuentes: [
      { nombre: "GBIF", quien: "Global Biodiversity Information Facility",
        uso: "Reúne los registros de aves y abejas de Santiago de muchas fuentes; de aquí se descargan todos.",
        url: "https://www.gbif.org/", enlace: "gbif.org" },
      { nombre: "eBird", quien: "Cornell Lab of Ornithology",
        uso: "Listas de aves que anotan observadores en todo el mundo; es la mayor parte de los registros de aves.",
        url: "https://ebird.org/", enlace: "ebird.org" },
      { nombre: "iNaturalist", quien: "California Academy of Sciences y National Geographic Society",
        uso: "Fotos de fauna con la especie confirmada por la comunidad («grado de investigación»); casi todos los registros de abejas.",
        url: "https://www.inaturalist.org/", enlace: "inaturalist.org" },
    ],
  },
  {
    id: "mapas", titulo: "Mapas", acento: "y grilla",
    fuentes: [
      { nombre: "Mapa base Positron", quien: "CARTO, con datos de OpenStreetMap",
        uso: "El fondo claro sobre el que se dibujan las cuadras.",
        url: "https://carto.com/basemaps", enlace: "carto.com/basemaps" },
      { nombre: "H3", quien: "Uber · código abierto",
        uso: "La grilla de hexágonos: resolución 9 para las cuadras y 7 para los barrios del aire y la fauna.",
        url: "https://h3geo.org/", enlace: "h3geo.org" },
      { nombre: "MapLibre GL JS", quien: "Proyecto MapLibre · código abierto",
        uso: "El motor que dibuja los mapas de la página.",
        url: "https://maplibre.org/", enlace: "maplibre.org" },
    ],
  },
];

export default function Fuentes() {
  // Las cuentas de escenas salen del mismo archivo que usa el histórico de la página principal.
  const serie = JSON.parse(readFileSync(path.join(process.cwd(), "public", "data", "historico.json"), "utf8"));
  const conCifras = (t: string) => t.replace("{landsat}", String(serie.escenas_landsat)).replace("{sentinel}", String(serie.escenas_sentinel2));
  return (
    <main className="b fuentes">
      <header className="b-pad bajo"><div className="b-in">
        <a className="marca" href="/"><img src="/viridis-logo.webp" alt="" width={34} height={34} />VIRIDIS</a>
        <nav aria-label="Secciones"><a href="/#ahora">Datos clave</a><a href="/#planificar">Planificar</a><a href="/#historico">Histórico</a><a href="/fuentes" aria-current="page">Fuentes</a></nav>
      </div></header>

      <section className="b-sec b-pad"><div className="b-in">
        <div className="b-cab">
          <h1>De dónde salen <em>los datos</em></h1>
          <p>Cada fuente, para qué la usamos y su sitio oficial. Todo es público.</p>
        </div>
        <nav className="f-indice" aria-label="Temas">
          {TEMAS.map((t) => (
            <Fragment key={t.id}>
              <a className="pill" href={`#${t.id}`}>{t.titulo} {t.acento}</a>
              {t.id === "personas" && <a className="pill" href="#vulnerabilidad">Vulnerabilidad al calor</a>}
            </Fragment>
          ))}
        </nav>
      </div></section>

      {TEMAS.map((t, k) => (
        <Fragment key={t.id}>
        <section id={t.id} className={`b-sec b-pad f-tema${k % 2 ? "" : " alt"}`}><div className="b-in">
          <h2>{t.titulo} <em>{t.acento}</em></h2>
          <ul className="f-lista">
            {t.fuentes.map((f) => (
              <li key={f.nombre}>
                <b>{f.nombre}</b>
                <span className="f-quien">{f.quien}</span>
                <p>{f.uso}</p>
                <a href={f.url} {...(f.url.startsWith("http") ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{f.enlace}{f.url.startsWith("http") ? " ↗" : ""}</a>
              </li>
            ))}
          </ul>
          {t.nota && <p className="nota f-nota">{conCifras(t.nota)}</p>}
          {t.mas && <a className="como" href={t.mas[0]}>{t.mas[1]}</a>}
        </div></section>
        {/* La vulnerabilidad va justo después de Personas, con el mismo fondo, como su método. */}
        {t.id === "personas" && <VulnerabilidadMetodo />}
        </Fragment>
      ))}

      <section className="b-sec b-pad"><div className="b-in" style={{ paddingBlock: "36px 56px" }}>
        <a className="pill llena grande" href="/" style={{ alignSelf: "flex-start" }}>← Volver al mapa</a>
      </div></section>
    </main>
  );
}
