"""Captura en terreno, sin red: índice de verde, agregación por hexágono, optimizador con terreno y servidor.

Uso: python -m tests.test_terreno
"""
import io
import tempfile
from pathlib import Path

import h3
import numpy as np
import pandas as pd
from PIL import Image

import terreno.vision as vision
from optimizer import solve_corridor
from terreno.almacen import Almacen, terreno_h3

DEMO = Path("data/santiago_h3.parquet")
GS = Path("data/santiago_h3_gs.parquet")
COMUNAS_DEMO = ["Providencia", "Cerro Navia"]


def filas(e: dict) -> list[dict]:
    """/api/estado manda los hexágonos en columnas; para los tests, una fila por hexágono."""
    col = e["hex"]
    return [dict(zip(col, v)) for v in zip(*col.values())]


def jpeg(rgb, tam=(320, 240)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", tam, rgb).save(b, "JPEG")
    return b.getvalue()


def test_indice_verde():
    assert vision.indice_verde(jpeg((40, 140, 40)))["verde_pct"] > 90
    assert vision.indice_verde(jpeg((128, 128, 128)))["verde_pct"] < 5
    mitad = Image.new("RGB", (200, 100), (128, 128, 128))
    mitad.paste((40, 140, 40), (0, 0, 100, 100))
    b = io.BytesIO(); mitad.save(b, "JPEG")
    assert 35 < vision.indice_verde(b.getvalue())["verde_pct"] < 65


def test_analizar_sin_claude():
    original = vision._cliente
    vision._cliente = lambda: None
    try:
        o = vision.analizar(jpeg((40, 140, 40)))
    finally:
        vision._cliente = original
    assert o["fuente"] == "indice_verde" and o["espacio_plantable"] is None and o["arbol_pct"] == o["verde_pct"]
    assert o["valida"] is None  # sin Claude no se sabe si es una calle


def obs(valida, plantable="medio", motivo=""):
    return vision.Observacion(valida=valida, motivo_rechazo=motivo, arbol_pct=0 if not valida else 20,
                              arbusto_pct=0, pasto_pct=0, suelo_desnudo_pct=0, construido_pct=0,
                              pavimento_pct=0 if not valida else 60, espacio_plantable=plantable,
                              obstaculos=[] if not valida else ["cables"], descripcion="")


def con_claude(resultado):
    """Reemplaza la llamada a Claude por un resultado fijo (sin red)."""
    original = vision.analizar_claude
    vision.analizar_claude = lambda jpeg, cliente=None: resultado
    return lambda: setattr(vision, "analizar_claude", original)


def test_validacion():
    from terreno.almacen import cuenta, estado_validacion
    deshacer = con_claude(obs(False, "ninguno", "Es un interior de oficina."))
    try:
        o = vision.analizar(jpeg((40, 140, 40)))
    finally:
        deshacer()
    assert o["valida"] is False and o["espacio_plantable"] is None and o["obstaculos"] == []
    assert estado_validacion(o) == "descartada" and not cuenta(o, True)
    assert estado_validacion({"valida": None}) == "sin_validar" and not cuenta({}) and cuenta({}, True)
    assert estado_validacion({"valida": True}) == "valida" and cuenta({"valida": True})


def cap(hx, pl, obst=(), arbol=10.0, t="2026-11-21T18:00:00+00:00", fuente="claude"):
    return {"h3_index": hx, "medido_en": t, "arbol_pct": arbol, "verde_pct": arbol + 5,
            "espacio_plantable": pl, "obstaculos": list(obst), "fuente": fuente}


def test_terreno_h3():
    a, b = "89b2c1a4a1bffff", "89b2c1a4a17ffff"
    df = terreno_h3([cap(a, "mucho", ["Cables"], 10), cap(a, "poco", ["cables", "vereda angosta"], 30,
                                                            "2026-11-21T19:00:00+00:00"),
                     cap(b, None, fuente="indice_verde")])
    fa, fb = df.set_index("h3_index").loc[a], df.set_index("h3_index").loc[b]
    assert fa.n_capturas == 2 and fa.arbol_pct_terreno == 20
    assert abs(fa.plantable - (1 + 0.33) / 2) < 1e-9
    assert abs(fa.viabilidad_terreno - (fa.plantable - 0.30)) < 1e-9  # 2 obstáculos distintos
    assert fa.obstaculos == "cables; vereda angosta" and fa.fuente == "claude"
    assert fa.ultima_captura == pd.Timestamp("2026-11-21T19:00:00+00:00")
    assert np.isnan(fb.viabilidad_terreno) and fb.fuente == "indice_verde"
    assert df["viabilidad_terreno"].dropna().between(0, 1).all()


def test_optimizador_con_terreno():
    df = pd.read_parquet(DEMO)
    base = solve_corridor(df)
    vacio = terreno_h3([])
    for t in (None, vacio):
        r = solve_corridor(df, terreno=t)
        assert r["hexes"] == base["hexes"] and r["verificados"] == 0
    # Un hexágono del corredor verificado como no plantable sale del grafo y el corredor cambia
    hx = next(h for h in base["hexes"] if not df.set_index("h3_index").loc[h, "es_parque"])
    r = solve_corridor(df, terreno=terreno_h3([cap(hx, "ninguno", ["cables"])]))
    assert hx not in r["hexes"] and r["hexes"] != base["hexes"]
    # Uno plantable y con muchos árboles en terreno queda verificado y baja su urgencia
    r2 = solve_corridor(df, terreno=terreno_h3([cap(hx, "mucho", arbol=90)]))
    assert r2["urgencia"][df["h3_index"] == hx].iloc[0] < base["urgencia"][df["h3_index"] == hx].iloc[0]
    if hx in r2["hexes"]:
        assert r2["verificados"] == 1


def test_servidor_validacion():
    """Una foto descartada por Claude o sin validar no cambia el corredor; una válida sí cuenta."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    df = pd.read_parquet(DEMO)
    hx = next(h for h in solve_corridor(df)["hexes"] if not df.set_index("h3_index").loc[h, "es_parque"])
    lat, lon = h3.cell_to_latlng(hx)
    form = {"lat": str(lat), "lon": str(lon)}
    foto = {"foto": ("c.jpg", jpeg((128, 128, 128)), "image/jpeg")}
    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(DEMO, Path(tmp), comunas=COMUNAS_DEMO))
        for resultado, esperado in ((obs(False, "ninguno", "Interior"), "descartada"), (None, "sin_validar")):
            deshacer = con_claude(resultado)
            try:
                d = c.post("/api/captura", data=form, files=foto).json()
            finally:
                deshacer()
            assert d["validacion"] == esperado and not d["cuenta"] and not d["corredor_cambio"]
            assert d["ahora"]["verificados"] == 0
        assert not any(h["verificado"] for h in filas(c.get("/api/estado").json()))
        deshacer = con_claude(obs(True, "ninguno"))  # válida y sin espacio: sale del corredor
        try:
            d = c.post("/api/captura", data=form, files=foto).json()
        finally:
            deshacer()
        assert d["validacion"] == "valida" and d["cuenta"] and d["corredor_cambio"]
        e = c.get("/api/estado").json()
        assert [x["validacion"] for x in e["capturas"]] == ["descartada", "sin_validar", "valida"]
        assert any(h["verificado"] for h in filas(e))


def test_servidor():
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    df = pd.read_parquet(DEMO)
    hx = solve_corridor(df)["hexes"][0]
    lat, lon = h3.cell_to_latlng(hx)
    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(DEMO, Path(tmp), comunas=COMUNAS_DEMO, clave="secreta", usar_claude=False, aceptar_sin_validar=True))
        assert c.get("/").status_code == 200 and c.get("/mapa").status_code == 200
        form = {"lat": str(lat), "lon": str(lon), "precision_m": "8"}
        foto = {"foto": ("c.jpg", jpeg((128, 128, 128)), "image/jpeg")}
        assert c.post("/api/captura", data=form, files=foto).status_code == 403
        r = c.post("/api/captura?k=secreta", data=form, files=foto)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["captura"]["h3_index"] == hx and not d["fuera_de_area"] and d["captura"]["fuente"] == "indice_verde"
        e = c.get("/api/estado").json()
        assert len(e["capturas"]) == 1 and any(h["verificado"] for h in filas(e))
        assert c.get(f"/fotos/{d['captura']['id']}_min.jpg").status_code == 200
        assert c.get("/fotos/..%2F..%2Fsecreto.jpg").status_code == 404
        assert (Path(tmp) / "terreno_h3.parquet").exists()
        r = c.post("/api/captura?k=secreta", data=form, files={"foto": ("x.jpg", b"no es imagen", "image/jpeg")})
        assert r.status_code == 422



def test_elegir_cuadros():
    from terreno.servidor import elegir_cuadros
    df = pd.read_parquet(DEMO)
    h1, h2 = df["h3_index"].iloc[0], df["h3_index"].iloc[1]
    p1, p2 = h3.cell_to_latlng(h1), h3.cell_to_latlng(h2)
    cuadros = [dict(lat=p1[0], lon=p1[1])] * 5 + [dict(lat=p2[0], lon=p2[1])] * 2
    assert elegir_cuadros(cuadros) == [0, 2, 5, 6]          # primero y del medio de cada tramo
    assert elegir_cuadros(cuadros, maximo=2) == [0, 5]      # con tope, uno por hexágono primero


def test_video():
    """Un recorrido: cuadros con posición y hora, trazado GPS y video; quedan guardados y cuentan si son válidos."""
    import json
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    df = pd.read_parquet(DEMO)
    hexes = [h for h in solve_corridor(df)["hexes"] if not df.set_index("h3_index").loc[h, "es_parque"]][:2]
    pts = [h3.cell_to_latlng(h) for h in hexes]
    cuadros = [{"lat": la, "lon": lo, "precision_m": 6, "t_s": 3 * i, "tomado_en": f"2026-11-21T18:00:0{i}Z"}
               for i, (la, lo) in enumerate([pts[0], pts[0], pts[1]])]
    track = [{**c, "t_s": c["t_s"]} for c in cuadros] + [{"lat": "malo", "lon": 0}]
    meta = json.dumps({"inicio": "2026-11-21T15:00:00-03:00", "cuadros": cuadros, "track": track})
    archivos = [("cuadros", (f"c{i}.jpg", jpeg((128, 128, 128)), "image/jpeg")) for i in range(3)]
    archivos.append(("video", ("r.webm", b"video falso", "video/webm")))
    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(DEMO, Path(tmp), comunas=COMUNAS_DEMO))
        deshacer = con_claude(obs(True, "mucho"))
        try:
            r = c.post("/api/video", data={"meta": meta}, files=archivos)
        finally:
            deshacer()
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["cuadros_recibidos"] == 3 and d["cuadros_analizados"] == 3 and d["validos"] == 3
        assert sorted(d["hexagonos"]) == sorted(hexes)
        assert d["recorrido"]["inicio"] == "2026-11-21T18:00:00+00:00" and d["recorrido"]["duracion_s"] == 6
        e = c.get("/api/estado").json()
        assert len(e["recorridos"]) == 1 and len(e["recorridos"][0]["linea"]) == 3  # el punto malo se descarta
        caps = e["capturas"]
        assert {x["video_id"] for x in caps} == {d["recorrido"]["id"]}
        assert caps[0]["tomado_en"] == "2026-11-21T18:00:00+00:00" and caps[0]["precision_m"] == 6
        assert c.get(f"/videos/{d['recorrido']['archivo']}").status_code == 200
        malo = c.post("/api/video", data={"meta": "{}"}, files=archivos[:1])
        assert malo.status_code == 422
        # foto suelta: guarda la hora del teléfono
        hx = hexes[0]
        la, lo = h3.cell_to_latlng(hx)
        f = c.post("/api/captura", data={"lat": la, "lon": lo, "tomado_en": "2026-11-21T15:30:00-03:00"},
                   files={"foto": ("c.jpg", jpeg((90, 90, 90)), "image/jpeg")}).json()
        assert f["captura"]["tomado_en"] == "2026-11-21T18:30:00+00:00" and f["captura"]["medido_en"]



def test_seleccion_comunas():
    """34 comunas: el corredor se calcula en las elegidas; se suman vecinas; por el túnel pide clave."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(GS, Path(tmp), clave="secreta", usar_claude=False))
        info = c.get("/api/comunas").json()
        assert len(info["comunas"]) == 34 and info["seleccion"] == ["Cerro Navia"]
        assert "Quinta Normal" in info["vecinas"]["Cerro Navia"] and "Maipú" not in info["vecinas"]["Cerro Navia"]
        assert all(a in info["vecinas"][b] for a in info["vecinas"] for b in info["vecinas"][a])  # simétrica
        e = c.get("/api/estado").json()
        df = pd.read_parquet(GS)
        assert len(filas(e)) == (df["comuna"] == "Cerro Navia").sum()
        r = c.post("/api/seleccion", json={"comunas": ["Quinta Normal", "Cerro Navia"]})
        assert r.status_code == 200 and r.json()["seleccion"] == ["Cerro Navia", "Quinta Normal"]
        e = c.get("/api/estado").json()
        assert len(filas(e)) == df["comuna"].isin(["Cerro Navia", "Quinta Normal"]).sum()
        assert set(df.set_index("h3_index").loc[[h["h"] for h in filas(e) if h["ahora"]], "comuna"]) <= {"Cerro Navia", "Quinta Normal"}
        r_vacio = c.post("/api/seleccion", json={"comunas": []})
        assert r_vacio.status_code == 200 and r_vacio.json()["seleccion"] == []
        assert filas(c.get("/api/estado").json()) == []
        assert c.post("/api/seleccion", json={"comunas": ["Narnia"]}).status_code == 422
        tunel = {"cf-connecting-ip": "1.2.3.4"}
        assert c.post("/api/seleccion", json={"comunas": ["Maipú"]}, headers=tunel).status_code == 403
        assert c.post("/api/seleccion?k=secreta", json={"comunas": ["Maipú"]}, headers=tunel).status_code == 200
        # una foto en otra comuna se guarda pero queda fuera de la selección
        la, lo = h3.cell_to_latlng(df.loc[df["comuna"] == "Providencia", "h3_index"].iloc[0])
        f = c.post("/api/captura?k=secreta", data={"lat": la, "lon": lo},
                   files={"foto": ("c.jpg", jpeg((90, 90, 90)), "image/jpeg")}).json()
        assert f["comuna"] == "Providencia" and f["fuera_de_seleccion"] and not f["fuera_de_area"]


def test_mapa_area_y_pesos():
    """Distritos, zona dibujada, presupuesto y pesos: cambian el área y el corredor de antes y de ahora."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app, distritos

    df = pd.read_parquet(GS)
    nombres = distritos(df)
    assert nombres == distritos(df.sample(frac=1, random_state=1))  # no depende del orden de las filas
    assert all(n.startswith(c + " - Distrito ") for (c, _), n in nombres.items())
    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(GS, Path(tmp), usar_claude=False, comunas=["Cerro Navia", "Quinta Normal"]))
        info = c.get("/api/comunas").json()
        assert all(n.startswith("Cerro Navia - ") for n in info["distritos"]["Cerro Navia"])
        v0 = c.get("/api/version").json()
        e = c.get("/api/estado").json()
        n_area = len(e["hex"]["h"])
        assert "pol" in e["hex"] and "pol" not in c.get(f"/api/estado?sel_id={e['sel_id']}").json()["hex"]
        d1 = info["distritos"]["Cerro Navia"][:2]
        r = c.post("/api/seleccion", json={"distritos": d1}).json()
        e = c.get("/api/estado").json()
        assert set(e["hex"]["distrito"]) == set(d1) and len(e["hex"]["h"]) < n_area
        assert r["parametros"]["distritos"] == sorted(d1) and e["sel_id"] != v0["sel_id"]
        # un distrito de una comuna no elegida se ignora; cambiar comunas descarta los que ya no aplican
        r = c.post("/api/seleccion", json={"comunas": ["Cerro Navia"]}).json()
        assert r["parametros"]["distritos"] == sorted(d1)
        r = c.post("/api/seleccion", json={"comunas": ["Quinta Normal"]}).json()
        assert r["parametros"]["distritos"] == []
        # zona: solo los hexágonos encerrados; una zona fuera del área no la vacía
        c.post("/api/seleccion", json={"comunas": ["Cerro Navia", "Quinta Normal"]})
        todos = c.get("/api/estado").json()["hex"]["h"]
        c.post("/api/seleccion", json={"zona": todos[:30]})
        assert sorted(c.get("/api/estado").json()["hex"]["h"]) == sorted(todos[:30])
        fuera = df.loc[df["comuna"] == "Maipú", "h3_index"].head(5).tolist()
        c.post("/api/seleccion", json={"zona": fuera})
        assert len(c.get("/api/estado").json()["hex"]["h"]) == len(todos)
        c.post("/api/seleccion", json={"zona": None})
        # presupuesto y pesos: antes y ahora los usan los dos
        base = c.get("/api/estado").json()
        r = c.post("/api/seleccion", json={"km": 8, "w_calor": 1, "w_arbol": 0, "w_personas": 0}).json()
        assert r["parametros"]["km"] == 8 and r["antes"] == r["ahora"]  # sin capturas: iguales
        assert r["ahora"]["km"] > base["ahora"]["km"]
        sub = df[df["comuna"].isin(["Cerro Navia", "Quinta Normal"])]
        esperado = solve_corridor(sub, 8, 1, 0, 0)
        assert r["ahora"]["hexes"] == len(esperado["hexes"])
        assert c.post("/api/seleccion", json={"w_calor": 0, "w_arbol": 0, "w_personas": 0}).status_code == 422
        assert c.post("/api/seleccion", json={"km": 100}).status_code == 422
        assert c.get("/api/version").json()["version"] > v0["version"]
        assert c.get("/api/salud").json() == {"ok": True}


def test_vivo_e_historico():
    """live_h3.parquet entra a la urgencia y se relee al cambiar; el histórico promedia el rango pedido."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    df = pd.read_parquet(GS)
    sub = df[df["comuna"] == "Cerro Navia"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        c = TestClient(crear_app(GS, tmp, usar_claude=False))
        sin_vivo = c.get("/api/estado").json()
        assert not sin_vivo["en_vivo"] and all(v is None for v in sin_vivo["hex"]["vivo"])
        v0 = c.get("/api/version").json()["version"]
        padres = sorted(sub["h3_padre"].unique())
        live = pd.DataFrame({"h3_padre": padres, "temp_aire_c": np.linspace(20, 35, len(padres)),
                             "confianza": "alta"})
        live.to_parquet(tmp / "live_h3.parquet")
        assert c.get("/api/version").json()["version"] > v0  # el sondeo nota el archivo nuevo
        e = c.get("/api/estado").json()
        assert e["en_vivo"] and all(x is not None for x in e["hex"]["vivo"])
        esperado = solve_corridor(sub, 3.0, live=live)["urgencia"].round(3).tolist()
        assert e["hex"]["u"] == esperado and e["hex"]["u"] != sin_vivo["hex"]["u"]
        # histórico sintético: dos meses para el primer hexágono, uno fuera del rango
        h0 = sub["h3_index"].iloc[0]
        pd.DataFrame({"mes": ["2024-01", "2024-02", "2025-06"], "h3_index": [h0] * 3,
                      "fecha": pd.to_datetime(["2024-01-10", "2024-02-10", "2025-06-01"]),
                      "ndvi": [0.2, 0.4, 0.9], "lst_c": [30.0, 34.0, 10.0]}).to_parquet(tmp / "historico_h3.parquet")
        r = c.get("/api/historico?desde=2024-01-01&hasta=2024-02-10").json()
        assert r["meses"] == 2 and r["h"] == [h0] and r["lst"] == [32.0] and r["ndvi"] == [0.3]
        assert c.get("/api/historico?desde=2025-01-01&hasta=2024-01-01").status_code == 422


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("OK", nombre)
