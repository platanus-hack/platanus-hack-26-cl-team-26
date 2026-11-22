// Sección de /fuentes: cómo se calcula la vulnerabilidad, lo mismo que hacen verdeh3/censo.py y
// verdeh3.contrato.vulnerabilidad, en palabras. Los rangos y las cifras por comuna salen de los datos de las 34 comunas
// (Censo 2024); si se regeneran los datos, actualizarlos aquí.

type Componente = { nombre: string; grupo: string; cuenta: string; por_que: string; rango: string };
const COMPONENTES: Componente[] = [
  { nombre: "Personas de 60 años o más", grupo: "Sensibilidad", cuenta: "n_edad_60_mas / personas",
    por_que: "Con la edad el cuerpo regula peor la temperatura y aparecen enfermedades que el calor agrava.",
    rango: "De 4,6 % a 34 % (mediana 20,7 %)" },
  { nombre: "Niños de 0 a 5 años", grupo: "Sensibilidad", cuenta: "n_edad_0_5 / personas",
    por_que: "Se deshidratan rápido y dependen de que un adulto los proteja del calor.",
    rango: "De 2,5 % a 10,9 % (mediana 5,3 %)" },
  { nombre: "Personas con discapacidad", grupo: "Sensibilidad", cuenta: "n_discapacidad / personas",
    por_que: "Pueden tener más difícil moverse a un lugar fresco o pedir ayuda. Es lo más cercano a salud que trae el Censo.",
    rango: "De 1,7 % a 16,6 % (mediana 8,8 %)" },
  { nombre: "Viviendas hacinadas", grupo: "Capacidad de adaptación", cuenta: "n_viv_hacinadas / viviendas ocupadas",
    por_que: "Más personas por pieza: la casa se calienta más y es más difícil encontrar un rincón fresco.",
    rango: "De 0,1 % a 16,5 % (mediana 4,3 %)" },
  { nombre: "Viviendas irrecuperables", grupo: "Capacidad de adaptación", cuenta: "n_viv_irrecuperables / viviendas ocupadas",
    por_que: "Materiales precarios (latas, desechos) que no aíslan: adentro hace tanto calor como afuera, o más.",
    rango: "De 0 % a 6,1 % (mediana 0,2 %)" },
  { nombre: "Años de escolaridad", grupo: "Capacidad de adaptación", cuenta: "prom_escolaridad18, invertida",
    por_que: "Indicador del nivel socioeconómico, que el Censo no pregunta como ingreso. Más años, menos vulnerable.",
    rango: "De 10,1 a 16,5 años (mediana 12,9)" },
];

const PASOS: { titulo: string; texto: string; formula: string }[] = [
  { titulo: "Del Censo a cada cuadra",
    texto: "El Censo 2024 publica sus datos por manzana. Cada cuadra del mapa (un hexágono H3 de resolución 9) se queda con la parte de cada manzana que cae dentro de ella, según el área que comparten. La escolaridad es un promedio, así que se reparte como suma ponderada por personas y después se divide.",
    formula: "conteo(cuadra) = Σ conteo(manzana) · área(manzana ∩ cuadra) / área(manzana)\nescolaridad(cuadra) = Σ escolaridad · personas  /  Σ personas" },
  { titulo: "Seis porcentajes",
    texto: "Edades y discapacidad se dividen por las personas de la cuadra; hacinamiento y viviendas irrecuperables, por las viviendas ocupadas. En cuadras con menos de 50 personas un solo vecino cambia el porcentaje en varios puntos, así que esas cuadras toman la mediana de su comuna (pasa en cerros, parques, industria y campo).",
    formula: "% 60 años o más = 100 · personas de 60+ / personas\n% hacinadas      = 100 · viviendas hacinadas / viviendas ocupadas" },
  { titulo: "Cada uno de 0 a 1",
    texto: "Cada porcentaje se lleva a una escala de 0 a 1 entre los percentiles 2 y 98 de las 34 comunas: el 2 % de cuadras más bajas queda en 0 y el 2 % más altas en 1, para que unos pocos casos extremos no aplasten al resto. La escala es siempre la de todo Santiago, aunque se mire una sola comuna.",
    formula: "norma(x) = recortar((x − p2) / (p98 − p2), 0, 1)" },
  { titulo: "Dos promedios y un promedio",
    texto: "Sensibilidad: qué tan frágil al calor es la gente que vive ahí. Capacidad de adaptación baja: qué tan difícil le es protegerse. Cada una es el promedio de sus tres componentes, con el mismo peso; la vulnerabilidad es el promedio de las dos.",
    formula: "sensibilidad   = [ norma(60+) + norma(0 a 5) + norma(discapacidad) ] / 3\nadaptación     = [ norma(hacinadas) + norma(irrecuperables) + 1 − norma(escolaridad) ] / 3\nvulnerabilidad = (sensibilidad + adaptación) / 2" },
];

const MENOS: [string, string][] = [["Providencia", "0,21"], ["Ñuñoa", "0,24"], ["Las Condes", "0,24"], ["Vitacura", "0,25"], ["Lo Barnechea", "0,26"]];
const MAS: [string, string][] = [["San Ramón", "0,56"], ["Lo Espejo", "0,56"], ["Cerro Navia", "0,55"], ["La Pintana", "0,55"], ["Pedro Aguirre Cerda", "0,54"]];

export function VulnerabilidadMetodo() {
  return (
    <section id="vulnerabilidad" className="b-sec b-pad f-tema alt v-metodo"><div className="b-in">
      <h2>Vulnerabilidad: <em>cómo se calcula</em></h2>
      <p className="v-intro">No todos sufren igual un día de 35 °C. Este índice mide, cuadra por cuadra, cuánto le pesa el calor a quienes viven ahí, de 0 a 1, con el Censo 2024.</p>

      <h3>Seis datos del Censo</h3>
      <ul className="f-lista">
        {COMPONENTES.map((c) => (
          <li key={c.nombre}>
            <b>{c.nombre}</b>
            <span className="f-quien">{c.grupo} · <code>{c.cuenta}</code></span>
            <p>{c.por_que}</p>
            <span className="v-rango">{c.rango}</span>
          </li>
        ))}
      </ul>
      <p className="nota f-nota">Rangos: percentiles 2 y 98 de las cuadras con 50 personas o más de las 34 comunas, que son los extremos de la escala de 0 a 1.</p>

      <h3>Paso a paso</h3>
      <ol className="v-pasos">
        {PASOS.map((p) => (
          <li key={p.titulo}>
            <b>{p.titulo}</b>
            <p>{p.texto}</p>
            <pre>{p.formula}</pre>
          </li>
        ))}
      </ol>
      <p className="nota f-nota">La separación en sensibilidad y capacidad de adaptación es la de los índices de vulnerabilidad más usados (exposición, sensibilidad y capacidad de adaptación); la exposición ya la mide el término de calor del índice de urgencia. Que los seis componentes pesen lo mismo es una decisión nuestra: no está calibrada contra muertes ni consultas por calor, porque no hay esos datos por cuadra.</p>

      <h3>En el corredor</h3>
      <ol className="v-pasos">
        <li>
          <b>Un término más de la urgencia</b>
          <p>En «Planificar», la urgencia de cada cuadra suma cuatro términos de 0 a 1. Por omisión la vulnerabilidad pesa 10 %; se puede mover con su control, y los pesos se reescalan para sumar 100 %.</p>
          <pre>{"urgencia = 35 % calor + 35 % falta de árboles + 20 % personas + 10 % vulnerabilidad"}</pre>
        </li>
        <li>
          <b>Solo para personas</b>
          <p>Es de quienes viven en la cuadra, no de las aves ni de las abejas: entra cuando el corredor se traza para Humanos (sola o junto a otras especies) y su control desaparece si Humanos no está marcado. En «Santiago conectado» la red fija no la usa, para que sus cifras sigan siendo comparables.</p>
        </li>
        <li>
          <b>Relativa a lo que eliges</b>
          <p>Como los demás términos, dentro de la urgencia la vulnerabilidad se vuelve a llevar de 0 a 1 entre las cuadras elegidas: si eliges solo Providencia, el corredor busca las cuadras más vulnerables de Providencia, aunque en la escala de todo Santiago sean bajas.</p>
        </li>
        <li>
          <b>Por qué 10 %</b>
          <p>Con más peso, quitado a «personas», el corredor de todo Santiago se iba a cuadras industriales con poca gente (1.436 personas, contra 7.002 de un trazado al azar). Con 10 % cubre 11.393 personas, y la gente que cubre es más vulnerable que el promedio de la ciudad: 0,52 contra 0,40.</p>
        </li>
      </ol>

      <h3>En Santiago</h3>
      <div className="v-tablas">
        {([["Menos vulnerables", MENOS], ["Más vulnerables", MAS]] as const).map(([titulo, filas]) => (
          <table key={titulo} className="v-tabla">
            <caption>{titulo}</caption>
            <tbody>{filas.map(([c, v]) => <tr key={c}><td>{c}</td><td className="num">{v}</td></tr>)}</tbody>
          </table>
        ))}
      </div>
      <p className="nota f-nota">Promedio por comuna ponderado por personas, en cuadras con 50 personas o más; todo Santiago: 0,40. La vulnerabilidad se parece poco al calor del suelo (correlación 0,13 por cuadra) y algo más a la falta de árboles (−0,35 con la copa): por eso agrega información al índice y no repite la que ya tenía.</p>

      <h3>Lo que no mide</h3>
      <ul className="v-limites">
        <li><b>Ingreso.</b> El Censo no lo pregunta; hacinamiento, viviendas irrecuperables y escolaridad hacen de aproximación.</li>
        <li><b>Enfermedades.</b> No hay datos de salud por cuadra: la discapacidad es lo más cercano.</li>
        <li><b>Quién vive solo.</b> Las personas mayores que viven solas están entre las más expuestas, y esta versión no lo cuenta.</li>
        <li><b>Personas, no cuadras exactas.</b> Repartir manzanas por área supone que la gente se distribuye pareja dentro de cada manzana.</li>
        <li><b>2024.</b> Es una foto del día del Censo, no de hoy.</li>
      </ul>
    </div></section>
  );
}
