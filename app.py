"""
VerdeH3 · Plataforma de Planificación de Corredores Verdes Urbanos
Gran Santiago (34 comunas · 13.172 hexágonos H3 resolución 9)
"""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from ecologia import PERFILES, calcular_resistencia_ecologica, resolver_corredor_por_perfil
from optimizer import solve_corridor, _norm

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y CSS
# ==========================================
st.set_page_config(
    page_title="VerdeH3 · Gran Santiago",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    html, body, [data-testid="stAppViewContainer"] {
        overflow-x: hidden !important;
    }
    [data-testid="stMainBlockContainer"],
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 1.5rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
        width: 100% !important;
        box-sizing: border-box !important;
    }
    h1, h2, h3, h4 {
        font-weight: 600;
        letter-spacing: -0.01em;
    }
    .legend-box {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 9px 14px;
        font-size: 13px;
        color: #e2e8f0;
        margin-bottom: 10px;
    }
    .footer-box {
        width: 100%;
        box-sizing: border-box;
        background-color: #0e1117;
        border: 1px solid #30363d;
        padding: 16px 20px;
        margin-top: 16px;
        border-radius: 6px;
        font-size: 12.5px;
        line-height: 1.6;
        color: #cbd5e1;
    }
    [data-testid="stDeckGlJsonChart"],
    .stDeckGlJsonChart {
        width: 100% !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

ALTURA_MAPA_LAPTOP = 560
BASE_DIR = Path(__file__).resolve().parent
RUTA_GS = BASE_DIR / "data" / "santiago_h3_gs.parquet"
RUTA_DEMO = BASE_DIR / "data" / "santiago_h3.parquet"
RUTA_LIVE = BASE_DIR / "data" / "live_h3.parquet"
RUTA_HIST = BASE_DIR / "data" / "historico_h3.parquet"
RUTA_HIST_META = BASE_DIR / "data" / "historico_meta.json"


# ==========================================
# CARGA DE DATOS Y PREPARACIÓN DE DISTRITOS
# ==========================================
@st.cache_data
def cargar_datos():
    ruta = RUTA_GS if RUTA_GS.exists() else RUTA_DEMO
    if not ruta.exists():
        st.error(f"No se encontró el archivo de datos: {ruta}")
        return pd.DataFrame()
    df = pd.read_parquet(ruta)

    if "h3_padre" in df.columns:
        padres = (
            df[["comuna", "h3_padre", "lat", "lon"]]
            .groupby(["comuna", "h3_padre"], as_index=False)
            .mean()
            .sort_values(["comuna", "lat", "lon"], ascending=[True, False, True])
        )
        padres["num"] = padres.groupby("comuna").cumcount() + 1
        padres["distrito"] = padres["comuna"] + " - Distrito " + padres["num"].astype(str)
        mapa_dist = dict(zip(padres["h3_padre"], padres["distrito"]))
        df["distrito"] = df["h3_padre"].map(mapa_dist)
    else:
        df["distrito"] = df["comuna"]

    return df


def cargar_live():
    if RUTA_LIVE.exists():
        try:
            return pd.read_parquet(RUTA_LIVE)
        except Exception:
            return None
    return None


@st.cache_data
def cargar_historico():
    if RUTA_HIST.exists():
        try:
            df_h = pd.read_parquet(RUTA_HIST)
            df_h["fecha"] = pd.to_datetime(df_h["fecha"]).dt.date
            meta = {}
            if RUTA_HIST_META.exists():
                meta = json.loads(RUTA_HIST_META.read_text())
            return df_h, meta
        except Exception:
            return pd.DataFrame(), {}
    return pd.DataFrame(), {}


# ==========================================
# FUNCIONES DE COLOR 2D Y MEZCLA RGB
# ==========================================
def interp_rgb(val_norm: np.ndarray, c_low: tuple, c_high: tuple) -> np.ndarray:
    v = np.clip(val_norm, 0.0, 1.0)[:, None]
    low = np.array(c_low, dtype=float)
    high = np.array(c_high, dtype=float)
    return low + v * (high - low)


def calcular_colores_capas(df: pd.DataFrame, usar_calor: bool, usar_verde: bool, usar_socio: bool) -> list:
    capas_rgb = []

    if usar_calor:
        calor_norm = _norm(df["lst_c"]).fillna(0.5).to_numpy()
        capas_rgb.append(interp_rgb(calor_norm, (255, 246, 229), (255, 95, 0)))

    if usar_verde:
        col_arbol = "copa_modelo_pct" if "copa_modelo_pct" in df.columns else "arbol_pct"
        verde_score = 0.6 * (df[col_arbol].clip(0, 100) / 100.0) + 0.4 * _norm(df["ndvi"]).fillna(0.5)
        verde_norm = _norm(verde_score).fillna(0.5).to_numpy()
        capas_rgb.append(interp_rgb(verde_norm, (235, 248, 235), (22, 163, 74)))

    if usar_socio:
        pob_norm = _norm(df["poblacion"]).fillna(0.5)
        soc_norm = df["social"].clip(0, 1).fillna(0.5)
        idx_soc = (0.5 * pob_norm + 0.5 * soc_norm).to_numpy()
        capas_rgb.append(interp_rgb(idx_soc, (238, 242, 255), (79, 70, 229)))

    if not capas_rgb:
        return [[200, 205, 215, 160]] * len(df)

    rgb_promedio = np.mean(capas_rgb, axis=0).astype(int)
    rgba = np.column_stack([rgb_promedio, np.full(len(df), 205, dtype=int)])
    return rgba.tolist()


def preparar_campos_tooltip(df: pd.DataFrame) -> pd.DataFrame:
    """Formatea columnas numéricas como texto limpio para que Deck.gl las muestre correctamente sin {}."""
    out = df.copy()
    col_arbol = "copa_modelo_pct" if "copa_modelo_pct" in out.columns else "arbol_pct"
    out["lst_fmt"] = out["lst_c"].round(1).astype(str)
    out["arbol_fmt"] = out[col_arbol].round(1).astype(str)
    out["ndvi_fmt"] = out["ndvi"].round(2).astype(str)
    out["social_fmt"] = out["social"].round(2).astype(str)
    out["poblacion_fmt"] = out["poblacion"].astype(int).map(lambda x: f"{x:,}")
    if "urgencia_calc" in out.columns:
        out["urgencia_fmt"] = out["urgencia_calc"].round(3).astype(str)
    if "intervencion_fmt" not in out.columns and "recomendado" in out.columns:
        out["recomendado_fmt"] = np.where(out["recomendado"], "Sí (Corredor Óptimo)", "No")
    return out


def render_mapa_2d(df_plot: pd.DataFrame, tooltip_html: str, zoom: float = 11.1):
    df_render = preparar_campos_tooltip(df_plot)
    lat_c = float(df_render["lat"].median())
    lon_c = float(df_render["lon"].median())

    capa = pdk.Layer(
        "H3HexagonLayer",
        df_render,
        pickable=True,
        stroked=True,
        filled=True,
        extruded=False,
        get_hexagon="h3_index",
        get_fill_color="color",
        get_line_color=[40, 45, 55, 80],
        line_width_min_pixels=1,
    )

    view = pdk.ViewState(
        latitude=lat_c,
        longitude=lon_c,
        zoom=zoom,
        pitch=0,
        bearing=0,
    )

    st.pydeck_chart(
        pdk.Deck(
            layers=[capa],
            initial_view_state=view,
            map_style="light",
            width="100%",
            height=ALTURA_MAPA_LAPTOP,
            tooltip={
                "html": tooltip_html,
                "style": {
                    "backgroundColor": "#161b22",
                    "color": "#f8fafc",
                    "fontSize": "12.5px",
                    "border": "1px solid #30363d",
                    "borderRadius": "6px",
                    "padding": "8px 10px",
                },
            },
        ),
        width="stretch",
        height=ALTURA_MAPA_LAPTOP,
    )


def render_selector_lazo(df_sel: pd.DataFrame, zoom: float):
    """Mapa interactivo con Plotly para encerrar con el mouse (lazo/caja) un trozo libre del mapa."""
    colores_css = [f"rgb({c[0]},{c[1]},{c[2]})" for c in df_sel["color"]]
    fig = go.Figure(
        go.Scattermap(
            lat=df_sel["lat"],
            lon=df_sel["lon"],
            mode="markers",
            marker=dict(size=10, color=colores_css, opacity=0.85),
            customdata=df_sel["h3_index"],
            text=df_sel["comuna"] + " - " + df_sel["distrito"],
            hoverinfo="text",
        )
    )
    fig.update_layout(
        map_style="carto-positron",
        map=dict(
            center=dict(lat=float(df_sel["lat"].median()), lon=float(df_sel["lon"].median())),
            zoom=zoom - 0.5,
        ),
        dragmode="lasso",
        margin=dict(l=0, r=0, t=0, b=0),
        height=ALTURA_MAPA_LAPTOP,
    )
    evento = st.plotly_chart(
        fig,
        width="stretch",
        height=ALTURA_MAPA_LAPTOP,
        on_select="rerun",
        selection_mode=("lasso", "box"),
        key="mapa_lazo_plotly",
    )
    if evento and getattr(evento, "selection", None) and evento.selection.get("points"):
        hexs_elegidos = [p["customdata"] for p in evento.selection["points"] if "customdata" in p]
        if hexs_elegidos:
            st.session_state["lazo_h3"] = set(hexs_elegidos)
            st.session_state["modo_lazo"] = False
            st.rerun()


def slider_con_numero(label: str, min_val: float, max_val: float, default: float, step: float, key_prefix: str, is_int: bool = False):
    """Sincroniza una barra deslizante y una caja de número manual."""
    k_num = f"{key_prefix}_num"
    k_sld = f"{key_prefix}_sld"
    if k_num not in st.session_state:
        st.session_state[k_num] = default
    if k_sld not in st.session_state:
        st.session_state[k_sld] = default

    def on_num_change():
        st.session_state[k_sld] = st.session_state[k_num]

    def on_sld_change():
        st.session_state[k_num] = st.session_state[k_sld]

    c1, c2 = st.columns([2.1, 1.0])
    with c1:
        st.slider(label, min_val, max_val, step=step, key=k_sld, on_change=on_sld_change)
    with c2:
        fmt = "%d" if is_int else "%.1f"
        st.number_input("Valor", min_val, max_val, step=step, format=fmt, key=k_num, on_change=on_num_change, label_visibility="collapsed")
    return st.session_state[k_sld]


# ==========================================
# INICIALIZACIÓN DE DATOS Y ESTADO
# ==========================================
df_base = cargar_datos()
live_df = cargar_live()
df_hist, hist_meta = cargar_historico()

if df_base.empty:
    st.stop()

todas_comunas = sorted(df_base["comuna"].dropna().unique().tolist())

MAPA_OPCIONES = [
    "Tiempo Real (Calor, Verde y Social)",
    "Optimizador Dijkstra",
    "Histórico (Promedio por Fechas)",
]

if "tipo_mapa" not in st.session_state or st.session_state["tipo_mapa"] not in MAPA_OPCIONES:
    st.session_state["tipo_mapa"] = MAPA_OPCIONES[0]
if "modo_lazo" not in st.session_state:
    st.session_state["modo_lazo"] = False
if "lazo_h3" not in st.session_state:
    st.session_state["lazo_h3"] = None

st.markdown("## VerdeH3 · Planificación de Corredores Verdes en Santiago")

# ==========================================
# ESTRUCTURA PRINCIPAL: FILTROS A LA IZQUIERDA | MAPA A LA DERECHA
# ==========================================
col_izq, col_der = st.columns([1.25, 2.75], gap="large")

with col_izq:
    st.markdown("### Filtros y Parámetros")

    with st.expander("Por Comuna y Por Distrito", expanded=True):
        modo_comuna = st.radio(
            "Comunas:",
            ["Todas (34 comunas)", "Piloto (Providencia vs Cerro Navia)", "Seleccionar comunas"],
            index=0,
        )
        if modo_comuna == "Todas (34 comunas)":
            comunas_sel = todas_comunas
        elif modo_comuna == "Piloto (Providencia vs Cerro Navia)":
            comunas_sel = [c for c in ["Providencia", "Cerro Navia"] if c in todas_comunas]
        else:
            comunas_sel = st.multiselect("Elegir comunas:", options=todas_comunas, default=todas_comunas[:4])
        if not comunas_sel:
            comunas_sel = todas_comunas

        df_por_comuna = df_base[df_base["comuna"].isin(comunas_sel)]
        distritos_disp = sorted(df_por_comuna["distrito"].dropna().unique().tolist())
        distritos_sel = st.multiselect(
            "Por Distrito (Barrio H3):",
            options=distritos_disp,
            default=[],
            placeholder="Todos los distritos de las comunas",
        )

    with st.expander("Selección Libre (Encerrar con Mouse)", expanded=True):
        c_l1, c_l2 = st.columns(2)
        with c_l1:
            if st.button("Encerrar zona", use_container_width=True, help="Dibuja un lazo con el mouse sobre el mapa para filtrar únicamente ese trozo"):
                st.session_state["modo_lazo"] = True
                st.rerun()
        with c_l2:
            if st.button("Limpiar trozo", use_container_width=True):
                st.session_state["lazo_h3"] = None
                st.session_state["modo_lazo"] = False
                st.rerun()

        if st.session_state["modo_lazo"]:
            st.info("Arrastra el mouse encerrando la zona deseada en el mapa de la derecha.")
        elif st.session_state["lazo_h3"]:
            st.success(f"Trozo libre activo: **{len(st.session_state['lazo_h3'])}** hexágonos seleccionados.")

    df_filtrado = df_por_comuna.copy()
    if distritos_sel:
        df_filtrado = df_filtrado[df_filtrado["distrito"].isin(distritos_sel)]
    if st.session_state["lazo_h3"] and not st.session_state["modo_lazo"]:
        df_sub = df_filtrado[df_filtrado["h3_index"].isin(st.session_state["lazo_h3"])]
        if not df_sub.empty:
            df_filtrado = df_sub

    zoom_mapa = 11.1 if (len(comunas_sel) > 8 and not distritos_sel and not st.session_state["lazo_h3"]) else 12.6

    tipo_actual = st.session_state["tipo_mapa"]

    if tipo_actual in (MAPA_OPCIONES[0], MAPA_OPCIONES[2]):
        st.markdown("#### Capas del Mapa 2D")
        st.caption("Puedes activar varias capas; su color se promediará.")
        f_calor = st.checkbox("Calor Superficial (Naranjo)", value=True, key="f_calor")
        f_verde = st.checkbox("Áreas Verdes (Verde)", value=False, key="f_verde")
        f_socio = st.checkbox(
            "Índice Social / Densidad",
            value=False,
            key="f_socio",
            help="Calculado como 50% Densidad Poblacional (WorldPop) + 50% Cercanía a Servicios Públicos (OSM).",
        )

        if tipo_actual == MAPA_OPCIONES[2]:
            st.markdown("#### Rango de Fechas")
            f_inicio = st.date_input("Desde (fecha i):", value=date(2024, 1, 1), min_value=date(2023, 1, 1), max_value=date(2026, 11, 21))
            f_fin = st.date_input("Hasta (fecha x):", value=date(2026, 11, 21), min_value=date(2023, 1, 1), max_value=date(2026, 11, 21))

    else:
        st.markdown("#### Objetivo de la Automatización")
        perfil_key = st.radio(
            "Diseñado pensando en:",
            options=list(PERFILES.keys()),
            format_func=lambda k: PERFILES[k],
            index=0,
            key="perfil_dijkstra",
        )
        salto_cp = 2
        if perfil_key == "fauna_abejas":
            salto_cp = st.slider("Separación máx. entre Mini Islas (hexágonos):", 1, 4, 2, 1,
                                 help="1 hexágono ≈ 350 m. Permite saltar entre islas verdes separadas.")

        st.markdown("#### Pesos Dijkstra y Presupuesto")
        st.caption("Usa las barras o escribe el número directamente:")
        budget_km = slider_con_numero("Presupuesto (km):", 1.0, 20.0, 3.0, 0.5, "budget")
        w_calor_raw = slider_con_numero("Calor (LST + Vivo):", 0, 100, 40, 5, "w_calor", is_int=True)
        w_arbol_raw = slider_con_numero("Falta de Árboles:", 0, 100, 40, 5, "w_arbol", is_int=True)
        w_pers_raw = slider_con_numero("Personas y Social:", 0, 100, 20, 5, "w_pers", is_int=True)

        total_w = w_calor_raw + w_arbol_raw + w_pers_raw
        if total_w == 0:
            w_calor_norm, w_arbol_norm, w_pers_norm = 0.4, 0.4, 0.2
            st.warning("Los pesos sumaban 0; usando 40% / 40% / 20%.")
        else:
            w_calor_norm = w_calor_raw / total_w
            w_arbol_norm = w_arbol_raw / total_w
            w_pers_norm = w_pers_raw / total_w

        st.markdown("**Distribución normalizada (%):**")
        st.write(f"Calor: **{w_calor_norm*100:.0f}%** | Árboles: **{w_arbol_norm*100:.0f}%** | Social: **{w_pers_norm*100:.0f}%**")
        st.progress(w_calor_norm)
        st.progress(w_arbol_norm)
        st.progress(w_pers_norm)


# ==========================================
# COLUMNA DERECHA: MAPA + SELECTOR ABAJO A LA DERECHA
# ==========================================
with col_der:
    tipo_actual = st.session_state["tipo_mapa"]

    # --------------------------------------
    # MAPA 1: TIEMPO REAL MULTICAPA
    # --------------------------------------
    if tipo_actual == MAPA_OPCIONES[0]:
        df_t1 = df_filtrado.copy()
        if "lst_c_ultima" in df_t1.columns:
            df_t1["lst_c"] = df_t1["lst_c_ultima"].fillna(df_t1["lst_c"])
        if live_df is not None and len(live_df):
            ok_live = live_df[live_df["confianza"].isin(["alta", "media"]) & live_df["temp_aire_c"].notna()]
            if len(ok_live):
                mapa_live = ok_live.groupby("h3_padre")["temp_aire_c"].last()
                df_t1["temp_vivo"] = df_t1["h3_padre"].map(mapa_live)
                df_t1["lst_c"] = df_t1["temp_vivo"].fillna(df_t1["lst_c"])

        col_copa = "copa_modelo_pct" if "copa_modelo_pct" in df_t1.columns else "arbol_pct"
        df_t1["color"] = calcular_colores_capas(df_t1, f_calor, f_verde, f_socio)

        leyenda = '<div class="legend-box"><b>Mapa 2D Tiempo Real:</b> &nbsp; '
        if f_calor:
            leyenda += '<b>Calor:</b> Claro → <span style="color:#ff5f00;font-weight:700;">Naranjo</span> &nbsp;|&nbsp; '
        if f_verde:
            leyenda += '<b>Áreas Verdes (Copa):</b> Claro → <span style="color:#16a34a;font-weight:700;">Verde</span> &nbsp;|&nbsp; '
        if f_socio:
            leyenda += '<b>Social/Densidad:</b> Claro → <span style="color:#4f46e5;font-weight:700;">Índigo</span>'
        if sum([f_calor, f_verde, f_socio]) > 1:
            leyenda += ' &nbsp;<i>(Color = promedio RGB)</i>'
        leyenda += "</div>"
        st.markdown(leyenda, unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Temp. Media", f"{df_t1['lst_c'].mean():.1f} °C")
        m2.metric("Temp. Máxima", f"{df_t1['lst_c'].max():.1f} °C")
        m3.metric("Copa Arbórea Media", f"{df_t1[col_copa].mean():.1f} %")
        m4.metric("Población (Censo 2024)", f"{int(df_t1['poblacion'].sum()):,}")

        if st.session_state["modo_lazo"]:
            render_selector_lazo(df_t1, zoom=zoom_mapa)
        else:
            tooltip_t1 = """
            <b>Comuna:</b> {comuna}<br/>
            <b>Distrito:</b> {distrito}<br/>
            <b>Temp. Superficial:</b> {lst_fmt} °C<br/>
            <b>Arbolado:</b> {arbol_fmt} %<br/>
            <b>NDVI:</b> {ndvi_fmt}<br/>
            <b>Índice Social (OSM):</b> {social_fmt}<br/>
            <b>Población:</b> {poblacion_fmt} hab.
            """
            render_mapa_2d(df_t1, tooltip_t1, zoom=zoom_mapa)

    # --------------------------------------
    # MAPA 2: ALGORITMO DIJKSTRA (HUMANOS vs FAUNA / MINI ISLAS)
    # --------------------------------------
    elif tipo_actual == MAPA_OPCIONES[1]:
        res_opt = resolver_corredor_por_perfil(
            df_filtrado,
            perfil=perfil_key,
            budget_km=budget_km,
            w_calor=w_calor_norm,
            w_arbol=w_arbol_norm,
            w_personas=w_pers_norm,
            live=live_df,
            salto_checkpoint=salto_cp,
        )

        df_t2 = df_filtrado.copy()
        df_t2["urgencia_calc"] = res_opt["score_mapa"].values
        hexes_corredor = set(res_opt["hexes_corredor"])
        hexes_cp = set(res_opt["hexes_checkpoints"])
        df_t2["recomendado"] = df_t2["h3_index"].isin(hexes_corredor | hexes_cp)

        # Etiqueta clara del tipo de intervención para tooltip
        df_t2["intervencion_fmt"] = "Matriz urbana"
        df_t2.loc[df_t2["es_parque"], "intervencion_fmt"] = "Parque / Isla verde existente"
        df_t2.loc[df_t2["h3_index"].isin(hexes_corredor), "intervencion_fmt"] = (
            "Ruta de vuelo entre checkpoints" if perfil_key == "fauna_abejas" else "Corredor arbóreo continuo"
        )
        if hexes_cp:
            df_t2.loc[df_t2["h3_index"].isin(hexes_cp), "intervencion_fmt"] = "Mini Isla (Checkpoint ecológico)"

        # Paleta sin azul para no confundir con agua:
        # Gris pizarra claro -> Verde medio -> Verde oscuro (corredor continuo)
        # Magenta (#c026d3) -> Mini Islas / Checkpoints
        # Ámbar (#d97706) -> Parques existentes
        u_arr = df_t2["urgencia_calc"].clip(0, 1).to_numpy()
        colors_t2 = interp_rgb(u_arr, (241, 245, 249), (74, 222, 128)).astype(int)
        alpha_t2 = np.full(len(df_t2), 165, dtype=int)

        mask_corr = df_t2["h3_index"].isin(hexes_corredor).to_numpy()
        if perfil_key == "fauna_abejas":
            # Ruta de conexión suave para resaltar los checkpoints encima
            colors_t2[mask_corr] = [134, 239, 172]
            alpha_t2[mask_corr] = 210
        else:
            colors_t2[mask_corr] = [21, 128, 61]
            alpha_t2[mask_corr] = 245

        mask_cp = df_t2["h3_index"].isin(hexes_cp).to_numpy()
        if mask_cp.any():
            colors_t2[mask_cp] = [192, 38, 211]
            alpha_t2[mask_cp] = 250

        mask_parque = df_t2["es_parque"].to_numpy() & (~mask_corr) & (~mask_cp)
        colors_t2[mask_parque] = [217, 119, 6]
        alpha_t2[mask_parque] = 185

        df_t2["color"] = np.column_stack([colors_t2, alpha_t2]).tolist()

        # Banner de objetivo activo + leyenda
        leyenda_cp = ' &nbsp;|&nbsp; <b>Mini Islas (Checkpoints):</b> <span style="color:#d946ef;font-weight:700;">Magenta</span>' if hexes_cp else ""
        st.markdown(
            f'<div class="legend-box"><b>Automatización activa: {PERFILES[perfil_key]}</b><br/>'
            f'<b>Corredor continuo:</b> <span style="color:#15803d;font-weight:700;">Verde oscuro</span>{leyenda_cp} &nbsp;|&nbsp; '
            f'<b>Parques existentes:</b> <span style="color:#d97706;font-weight:700;">Ámbar</span></div>',
            unsafe_allow_html=True,
        )

        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Intervención", f"{res_opt['length_km']:.2f} km", f"{len(hexes_corredor | hexes_cp)} hexágonos")
        d2.metric("Parques Conectados", f"{res_opt['parques_conectados']}", f"{len(res_opt['tramos'])} tramos")
        if hexes_cp:
            d3.metric("Mini Islas (Checkpoints)", f"{len(hexes_cp)}", "Bosques de bolsillo")
        else:
            d3.metric("Resistencia Ecológica", f"{res_opt['resistencia_media']:.1f} / 100", "Menor = más fácil cruzar")
        d4.metric("Personas Cubiertas", f"{res_opt['personas_cubiertas']:,}")

        if st.session_state["modo_lazo"]:
            render_selector_lazo(df_t2, zoom=zoom_mapa)
        else:
            tooltip_t2 = """
            <b>Comuna:</b> {comuna}<br/>
            <b>Distrito:</b> {distrito}<br/>
            <b>Rol en Diseño:</b> {intervencion_fmt}<br/>
            <b>Score / Prioridad:</b> {urgencia_fmt}<br/>
            <b>Temp. Superficial:</b> {lst_fmt} °C<br/>
            <b>Copa Arbórea:</b> {arbol_fmt} %
            """
            render_mapa_2d(df_t2, tooltip_t2, zoom=zoom_mapa)

    # --------------------------------------
    # MAPA 3: HISTÓRICO POR FECHAS (SATELITAL REAL)
    # --------------------------------------
    else:
        if f_inicio > f_fin:
            st.error("La fecha 'Desde' debe ser anterior o igual a la fecha 'Hasta'.")
        else:
            df_t3 = df_filtrado.copy()
            n_meses_reales = 0

            if not df_hist.empty:
                sub_h = df_hist[(df_hist["fecha"] >= f_inicio) & (df_hist["fecha"] <= f_fin)]
                if not sub_h.empty:
                    n_meses_reales = sub_h["mes"].nunique()
                    prom_h = sub_h.groupby("h3_index", as_index=False)[["lst_c", "ndvi"]].mean()
                    prom_h = prom_h.rename(columns={"lst_c": "lst_hist", "ndvi": "ndvi_hist"})
                    df_t3 = df_t3.merge(prom_h, on="h3_index", how="left")
                    df_t3["lst_c"] = df_t3["lst_hist"].fillna(df_t3["lst_c"])
                    df_t3["ndvi"] = df_t3["ndvi_hist"].fillna(df_t3["ndvi"]).clip(0, 1)

            df_t3["color"] = calcular_colores_capas(df_t3, f_calor, f_verde, f_socio)
            dias_rango = max(1, (f_fin - f_inicio).days + 1)

            if n_meses_reales > 0:
                st.markdown(
                    f'<div class="legend-box"><b>Promedio Satelital Real ({f_inicio} → {f_fin}):</b> {n_meses_reales} meses con capturas Landsat/Sentinel-2 promediados · Escala de colores equivalente al Mapa 1</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="legend-box"><b>Período ({f_inicio} → {f_fin}, {dias_rango} días):</b> Sin escenas históricas en este sub-rango exacto; mostrando referencia base</div>',
                    unsafe_allow_html=True,
                )

            h1, h2, h3 = st.columns(3)
            h1.metric("Temp. Promedio Rango", f"{df_t3['lst_c'].mean():.1f} °C")
            h2.metric("NDVI Promedio Rango", f"{df_t3['ndvi'].mean():.3f}")
            h3.metric("Meses Satelitales", f"{n_meses_reales}" if n_meses_reales > 0 else "Base")

            if st.session_state["modo_lazo"]:
                render_selector_lazo(df_t3, zoom=zoom_mapa)
            else:
                tooltip_t3 = """
                <b>Comuna:</b> {comuna}<br/>
                <b>Distrito:</b> {distrito}<br/>
                <b>Temp. Promedio Período:</b> {lst_fmt} °C<br/>
                <b>NDVI Promedio Período:</b> {ndvi_fmt}<br/>
                <b>Arbolado:</b> {arbol_fmt} %
                """
                render_mapa_2d(df_t3, tooltip_t3, zoom=zoom_mapa)

    # --------------------------------------
    # SELECTOR DE TIPO DE MAPA (ABAJO A LA DERECHA)
    # --------------------------------------
    c_vacio, c_sel_mapa = st.columns([1.0, 2.0])
    with c_sel_mapa:
        st.radio(
            "Seleccionar Tipo de Mapa:",
            options=MAPA_OPCIONES,
            key="tipo_mapa",
            horizontal=True,
        )

# ==========================================
# PIE DE PÁGINA: DATASETS Y UBICACIÓN
# ==========================================
info_hist_txt = "Serie histórica mensual real (2023-01 a 2026-11)"
if hist_meta:
    info_hist_txt = (
        f"{hist_meta.get('meses_totales', 0)} meses ({hist_meta.get('mes_min', '2023-01')} a {hist_meta.get('mes_max', '2026-11')}): "
        f"{hist_meta.get('escenas_landsat', 0)} escenas Landsat 8/9 y {hist_meta.get('escenas_sentinel2', 0)} escenas Sentinel-2"
    )

st.markdown("---")
st.markdown(
    f"""
<div class="footer-box">
    <div style="font-size:14px; font-weight:700; color:#f3f4f6; margin-bottom:8px;">
        Fuentes de Datos y Datasets Utilizados (Gran Santiago · Grilla H3 Res. 9)
    </div>
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap:12px;">
        <div>
            • <b>Base Geoespacial Unificada:</b> <code>data/santiago_h3_gs.parquet</code> (34 comunas, 13.172 hexágonos H3) y <code>data/santiago_h3.parquet</code> (demo).<br/>
            • <b>Serie Histórica Satelital Real:</b> <code>data/historico_h3.parquet</code> ({info_hist_txt}) vía Microsoft Planetary Computer.<br/>
            • <b>Modelo de Copa de Árboles:</b> Modelo propio Gradient Boosting (<code>verdeh3.modelo_copa</code>, <code>datos/modelo_copa.joblib</code>) sobre Sentinel-2 2026 entrenado con Meta/WRI 1m (r = 0.92).<br/>
            • <b>Temperatura Superficial (LST):</b> Landsat 8/9 C2 L2 (escenas verano y reciente) → <code>datos/cache_gs/lst_*.tif</code>.
        </div>
        <div>
            • <b>Población:</b> Censo de Población y Vivienda 2024 (INE, nivel manzana) → <code>verdeh3/censo.py</code>.<br/>
            • <b>Sensores en Vivo por Barrio (H3 Res. 7):</b> DMC, SINCA y Sensor.Community → <code>data/live_h3.parquet</code>.<br/>
            • <b>Equipamiento y Parques (Índice Social y <code>es_parque</code>):</b> OpenStreetMap (colegios, salud, metro, paraderos y parques ≥ 5.000 m²) → <code>datos/salida_h3_gs/capas_osm.gpkg</code>.<br/>
            • <b>Cobertura de Suelo (referencia):</b> ESA WorldCover 2021 v200 → <code>datos/cache_gs/worldcover_2021.tif</code>.
        </div>
    </div>
    <div style="margin-top:10px; padding-top:8px; border-top:1px solid #30363d; color:#94a3b8;">
        <i>Nota metodológica: El indicador "Índice Social / Densidad" combina 50% densidad poblacional (Censo 2024 INE) y 50% cercanía a servicios públicos (OSM), no proviene de encuestas de ingresos (CASEN/GSE). El mapa histórico calcula promedios reales sobre las escenas satelitales descargadas en el rango seleccionado.</i>
    </div>
</div>
""",
    unsafe_allow_html=True,
)
