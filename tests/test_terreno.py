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


def obs(valida, plantable="medio", motivo="", tipo="calle", fauna=(), flores="ninguna"):
    return vision.Observacion(valida=valida, motivo_rechazo=motivo, tipo_foto=tipo, arbol_pct=0 if not valida else 20,
                              arbusto_pct=0, pasto_pct=0, suelo_desnudo_pct=0, construido_pct=0,
                              pavimento_pct=0 if not valida else 60, espacio_plantable=plantable,
                              obstaculos=[] if not valida else ["cables"],
                              fauna=[vision.Avistamiento(**a) for a in fauna], flores=flores, descripcion="")


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
        assert [x["validacion"] for x in c.get("/api/capturas").json()["capturas"]] == ["descartada", "sin_validar", "valida"]
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
        assert len(c.get("/api/capturas").json()["capturas"]) == 1 and any(h["verificado"] for h in filas(e))
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
        caps = c.get("/api/capturas").json()["capturas"]
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
        assert len(info["comunas"]) == 34 and info["seleccion"] == info["comunas"]  # al abrir, todas
        df = pd.read_parquet(GS)
        from terreno.servidor import sin_islas
        hs = c.get("/api/estado").json()["hex"]["h"]
        # El trozo suelto de San Bernardo (24 cuadras sin gente, resto del recorte) no se muestra; no se pierde nadie.
        suelto = df[~df["h3_index"].isin(hs)]
        assert len(hs) == len(sin_islas(df)) == len(df) - 24
        assert set(suelto["comuna"]) == {"San Bernardo"} and suelto["poblacion"].sum() == 0 and not suelto["es_parque"].any()
        c.post("/api/seleccion", json={"comunas": ["Cerro Navia"]})
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
        r = c.post("/api/seleccion", json={"km": 8, "w_calor": 1, "w_arbol": 0, "w_personas": 0, "w_bio": 0}).json()
        assert r["parametros"]["km"] == 8 and r["antes"] == r["ahora"]  # sin capturas: iguales
        assert r["ahora"]["km"] > base["ahora"]["km"]
        sub = df[df["comuna"].isin(["Cerro Navia", "Quinta Normal"])]
        esperado = solve_corridor(sub, 8, 1, 0, 0)
        assert r["ahora"]["hexes"] == len(esperado["hexes"])
        assert c.post("/api/seleccion", json={"w_calor": 0, "w_arbol": 0, "w_personas": 0, "w_bio": 0}).status_code == 422
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
        c = TestClient(crear_app(GS, tmp, usar_claude=False, comunas=["Cerro Navia"]))
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
        esperado = solve_corridor(sub, 3.0, live=live, w_bio=0.1)["urgencia"].round(3).tolist()  # peso inicial del servidor
        assert e["hex"]["u"] == esperado and e["hex"]["u"] != sin_vivo["hex"]["u"]
        # histórico sintético: dos meses para el primer hexágono, uno fuera del rango
        h0 = sub["h3_index"].iloc[0]
        pd.DataFrame({"mes": ["2024-01", "2024-02", "2025-06"], "h3_index": [h0] * 3,
                      "fecha": pd.to_datetime(["2024-01-10", "2024-02-10", "2025-06-01"]),
                      "ndvi": [0.2, 0.4, 0.9], "lst_c": [30.0, 34.0, 10.0]}).to_parquet(tmp / "historico_h3.parquet")
        r = c.get("/api/historico?desde=2024-01-01&hasta=2024-02-10").json()
        assert r["meses"] == 2 and r["h"] == [h0] and r["lst"] == [32.0] and r["ndvi"] == [0.3]
        assert c.get("/api/historico?desde=2025-01-01&hasta=2024-01-01").status_code == 422


def wav(segundos=2.0, tasa=44100, amplitud=0.05) -> bytes:
    """WAV PCM 16 bit mono de ruido, como el que arma la página del teléfono (amplitud alta = calle ruidosa)."""
    import wave
    x = (np.clip(amplitud * np.random.default_rng(0).standard_normal(int(segundos * tasa)), -1, 1) * 32767).astype("<i2")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(tasa); w.writeframes(x.tobytes())
    return b.getvalue()


def test_fauna_flora():
    """Un primer plano de una abeja en flores es válido, suma biodiversidad y no toca copa ni espacio plantable."""
    abeja = [{"grupo": "abeja", "nombre": "", "cantidad": 3}]
    deshacer = con_claude(obs(True, plantable="ninguno", tipo="fauna_flora", fauna=abeja, flores="muchas"))
    try:
        o = vision.analizar(jpeg((200, 180, 40)))
    finally:
        deshacer()
    assert o["valida"] and o["tipo_foto"] == "fauna_flora"
    assert o["espacio_plantable"] is None and o["arbol_pct"] is None and o["obstaculos"] == []
    hx = "89b2c1a4a1bffff"
    f = terreno_h3([{**o, "h3_index": hx, "medido_en": "2026-11-21T18:00:00+00:00"}]).iloc[0]
    assert np.isnan(f.viabilidad_terreno) and np.isnan(f.arbol_pct_terreno)  # no excluye ni cambia la copa
    assert f.n_polinizadores == 3 and f.flores == 1.0
    assert abs(f.biodiversidad_terreno - (0.3 + 0.2)) < 1e-9
    # una foto inválida no trae fauna aunque Claude la haya listado
    deshacer = con_claude(obs(False, motivo="interior", fauna=abeja))
    try:
        assert vision.analizar(jpeg((90, 90, 90)))["fauna"] == []
    finally:
        deshacer()


def test_biodiversidad():
    """Aves oídas (BirdNET) y vistas (Claude) se juntan por especie; el puntaje queda entre 0 y 1."""
    a, b = "89b2c1a4a1bffff", "89b2c1a4a17ffff"
    caps = [{**cap(a, "medio"), "fauna": [{"grupo": "ave", "nombre": "Zorzal", "cantidad": 1},
                                          {"grupo": "mariposa", "nombre": "", "cantidad": 2}], "flores": "pocas"},
            {**cap(b, "medio"), "fauna": [{"grupo": "ave", "nombre": "", "cantidad": 4}], "flores": "ninguna"}]
    det = lambda *n: [{"cientifico": x, "comun": x, "confianza": 0.8, "inicio_s": 0, "fin_s": 3} for x in n]
    escuchas = [{"h3_index": a, "medido_en": "2026-11-21T19:00:00+00:00", "detecciones": det("Turdus falcklandii", "Zenaida auriculata")},
                {"h3_index": "89b2c1a4a07ffff", "medido_en": "2026-11-21T19:00:00+00:00", "detecciones": det("Turdus falcklandii")}]
    df = terreno_h3(caps, escuchas).set_index("h3_index")
    fa = df.loc[a]
    assert fa.n_especies_aves == 3 and fa.n_escuchas == 1 and fa.n_polinizadores == 2  # zorzal visto + 2 oídas
    assert abs(fa.biodiversidad_terreno - (0.5 * 3 / 5 + 0.3 + 0.2 * 0.5)) < 1e-9
    assert df.loc[b].especies_aves == "ave sin identificar" and df.loc[b].n_especies_aves == 1
    solo = df.loc["89b2c1a4a07ffff"]  # solo escucha: no es una foto, no verifica ni toca la copa
    assert solo.n_capturas == 0 and np.isnan(solo.arbol_pct_terreno) and solo.fuente == "birdnet"
    assert df["biodiversidad_terreno"].between(0, 1).all()
    tres = [{"grupo": "abeja", "nombre": "", "cantidad": 3}]
    mismas = terreno_h3([{**cap(a, "medio"), "fauna": tres}, {**cap(a, "medio"), "fauna": tres}]).iloc[0]
    assert mismas.n_polinizadores == 3  # dos fotos de las mismas abejas no son 6
    # optimizador: w_bio=0 no cambia nada; con w_bio el hexágono con fauna sube de urgencia
    from optimizer import urgencia
    base = pd.read_parquet(DEMO)
    hx = base["h3_index"].iloc[10]
    t = pd.DataFrame({"h3_index": [hx], "n_capturas": [0], "arbol_pct_terreno": [np.nan],
                      "viabilidad_terreno": [np.nan], "biodiversidad_terreno": [1.0]})
    u0, u_t = urgencia(base), urgencia(base, terreno=t)
    assert u0.equals(u_t) and solve_corridor(base)["hexes"] == solve_corridor(base, terreno=t)["hexes"]
    u_b = urgencia(base, terreno=t, w_bio=0.5)
    otros = base["h3_index"] != hx
    assert np.allclose(u_b[otros], u0[otros] / 1.5)  # los demás solo se reescalan
    assert u_b[~otros].iloc[0] > u0[~otros].iloc[0] / 1.5
    assert solve_corridor(base, terreno=t, w_bio=0.5)["verificados"] == 0  # una escucha no es verificación


def test_audio():
    """Escucha de aves: guarda el WAV y la posición, BirdNET (simulado) identifica y el corredor se recalcula."""
    from fastapi.testclient import TestClient
    import terreno.aves as aves
    from terreno.servidor import crear_app

    df = pd.read_parquet(DEMO)
    hx = solve_corridor(df)["hexes"][1]
    la, lo = h3.cell_to_latlng(hx)
    original = aves.detectar
    llamadas = []

    def falso(datos, lat, lon, fecha=None):
        llamadas.append((lat, lon, fecha))
        return [{"cientifico": "Turdus falcklandii", "comun": "Austral Thrush", "confianza": 0.91,
                 "inicio_s": 3.0, "fin_s": 6.0}]
    aves.detectar = falso
    try:
        with tempfile.TemporaryDirectory() as tmp:
            c = TestClient(crear_app(DEMO, Path(tmp), comunas=COMUNAS_DEMO, clave="secreta", usar_claude=False))
            v0 = c.get("/api/version").json()["version"]
            pag = c.get("/captura?k=secreta")  # la misma página del teléfono, para el sitio web/
            assert pag.status_code == 200 and "Escuchar aves" in pag.text and pag.text == c.get("/").text
            datos = {"lat": la, "lon": lo, "precision_m": 8, "tomado_en": "2026-11-21T15:00:00-03:00"}
            assert c.post("/api/audio", data=datos, files={"audio": ("a.wav", wav(), "audio/wav")}).status_code == 403
            r = c.post("/api/audio?k=secreta", data=datos, files={"audio": ("a.wav", wav(), "audio/wav")})
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["analizada"] and d["escucha"]["h3_index"] == hx and d["en_corredor"]
            assert d["escucha"]["tomado_en"] == "2026-11-21T18:00:00+00:00" and abs(d["escucha"]["duracion_s"] - 2) < 0.1
            assert llamadas[0][2] is not None and llamadas[0][2].hour == 18  # BirdNET recibe la fecha para filtrar especies
            e = c.get("/api/estado").json()
            assert e["version"] > v0 and len(c.get("/api/capturas").json()["escuchas"]) == 1
            fila = next(f for f in filas(e) if f["h"] == hx)
            assert fila["bio"] == 0.1 and fila["especies"] == "Turdus falcklandii" and not fila["verificado"]
            assert e["fauna_corredor"]["especies"] == ["Turdus falcklandii"]
            nombre = d["escucha"]["id"] + ".wav"
            assert c.get(f"/audios/{nombre}").content[:4] == b"RIFF"
            assert c.get("/audios/..%2Fescuchas.jsonl").status_code == 404
            malo = c.post("/api/audio?k=secreta", data=datos, files={"audio": ("a.wav", b"no es audio", "audio/wav")})
            assert malo.status_code == 422
            # sin BirdNET el audio se guarda «sin analizar» y no suma biodiversidad
            aves.detectar = lambda *a, **k: None
            d2 = c.post("/api/audio?k=secreta", data=datos, files={"audio": ("a.wav", wav(), "audio/wav")}).json()
            assert not d2["analizada"] and len(c.get("/api/capturas").json()["escuchas"]) == 2
            assert d["escucha"]["ruido"]["nivel"] in ("bajo", "medio", "alto") and d["escucha"]["concluyente"]
            # sin aves y con tráfico fuerte: «no concluyente»
            aves.detectar = lambda *a, **k: []
            d3 = c.post("/api/audio?k=secreta", data=datos,
                        files={"audio": ("a.wav", wav(amplitud=0.4), "audio/wav")}).json()
            assert d3["escucha"]["ruido"]["nivel"] == "alto" and d3["escucha"]["concluyente"] is False
            assert next(f for f in filas(c.get("/api/estado").json()) if f["h"] == hx)["bio"] == 0.1
    finally:
        aves.detectar = original


def test_ruido_y_tramos():
    """El ruido mide la banda del tráfico; un canto agudo no es ruido. El audio de un paseo se parte por hexágono."""
    import terreno.aves as aves
    sr = 32000
    t = np.arange(sr * 4) / sr
    rng = np.random.default_rng(0)
    trafico = (0.08 * rng.standard_normal(len(t)) + 0.1 * np.sin(2 * np.pi * 120 * t)).astype(np.float32)
    canto = (0.002 * rng.standard_normal(len(t)) + 0.3 * np.sin(2 * np.pi * 4000 * t)).astype(np.float32)
    r_t, r_c = (aves.resumir_ruido(aves.ruido_por_segundo(x, sr)) for x in (trafico, canto))
    assert r_t["nivel"] == "alto" and r_c["nivel"] == "bajo" and len(aves.ruido_por_segundo(trafico, sr)) == 4
    assert aves.resumir_ruido([-60, -20, -61])["db"] == -60  # la mediana ignora una bocina
    assert not aves.concluyente([], r_t) and aves.concluyente([], r_c) and aves.concluyente([{"x": 1}], r_t)
    assert aves.concluyente(None, None)
    a_, b_ = "89b2c1a4a1bffff", "89b2c1a4a17ffff"
    (la, lo), (lb, lob) = h3.cell_to_latlng(a_), h3.cell_to_latlng(b_)
    track = [{"lat": la, "lon": lo, "t_s": 0}, {"lat": la, "lon": lo, "t_s": 4},
             {"lat": lb, "lon": lob, "t_s": 8}, {"lat": la, "lon": lo, "t_s": 8.6}]  # vuelta corta: se descarta
    tr = aves.tramos_por_hexagono(track, 9.0)
    assert [x["h3_index"] for x in tr] == [a_, b_]
    assert tr[0]["desde_s"] == 0 and tr[0]["hasta_s"] == 6.0 and tr[1]["desde_s"] == 6.0 and tr[1]["hasta_s"] == 8.3
    assert aves.tramos_por_hexagono([], 10) == []


def test_paseo_con_audio():
    """Video caminando con micrófono: cada ave queda en el hexágono donde iba el teléfono cuando cantó."""
    import json
    from fastapi.testclient import TestClient
    import terreno.aves as aves
    from terreno.servidor import crear_app

    df = pd.read_parquet(DEMO)
    hexes = [h for h in solve_corridor(df)["hexes"] if not df.set_index("h3_index").loc[h, "es_parque"]][:2]
    (la, lo), (lb, lob) = (h3.cell_to_latlng(h) for h in hexes)
    track = [{"lat": la, "lon": lo, "precision_m": 5, "t_s": t} for t in (0, 3, 6)] + \
            [{"lat": lb, "lon": lob, "precision_m": 5, "t_s": t} for t in (9, 12, 15)]
    cuadros = [track[0], track[3]]
    meta = json.dumps({"inicio": "2026-11-21T15:00:00-03:00", "cuadros": cuadros, "track": track})
    fotos = [("cuadros", (f"c{i}.jpg", jpeg((128, 128, 128)), "image/jpeg")) for i in range(2)]
    original = aves.detectar_crudo
    vistos = []

    def falso(x, tasa, lat, lon, fecha=None):
        vistos.append((len(x) / tasa, lat, fecha))
        d = lambda n, t0, c: {"cientifico": n, "comun": n, "confianza": c, "inicio_s": t0, "fin_s": t0 + 3}
        return [d("Turdus falcklandii", 0, 0.6), d("Turdus falcklandii", 3, 0.9), d("Zenaida auriculata", 12, 0.7)]
    aves.detectar_crudo = falso
    try:
        with tempfile.TemporaryDirectory() as tmp:
            c = TestClient(crear_app(DEMO, Path(tmp), comunas=COMUNAS_DEMO))
            deshacer = con_claude(obs(True, "medio"))
            try:
                r = c.post("/api/video", data={"meta": meta},
                           files=fotos + [("audio", ("r.wav", wav(16, 32000, amplitud=0.3), "audio/wav"))])
                sin_audio = c.post("/api/video", data={"meta": meta}, files=fotos).json()
                malo = c.post("/api/video", data={"meta": meta},
                              files=fotos + [("audio", ("r.wav", b"no", "audio/wav"))]).json()
            finally:
                deshacer()
            assert r.status_code == 200, r.text
            d = r.json()
            assert abs(vistos[0][0] - 16) < 0.01 and vistos[0][1] == la and vistos[0][2].hour == 18
            a = d["aves"]
            assert a["analizada"] and a["tramos"] == 2 and a["ruido"]["nivel"] == "alto"
            assert [x["cientifico"] for x in a["especies"]] == ["Turdus falcklandii", "Zenaida auriculata"]
            esc = {e["h3_index"]: e for e in c.get("/api/capturas").json()["escuchas"]}
            ea, eb = esc[hexes[0]], esc[hexes[1]]
            assert [x["cientifico"] for x in ea["detecciones"]] == ["Turdus falcklandii"]
            assert ea["detecciones"][0]["confianza"] == 0.9  # la mejor de sus dos detecciones
            assert [x["cientifico"] for x in eb["detecciones"]] == ["Zenaida auriculata"]
            assert ea["video_id"] == eb["video_id"] == d["recorrido"]["id"] and ea["archivo"] == eb["archivo"]
            assert ea["desde_s"] == 0 and ea["hasta_s"] == eb["desde_s"] == 7.5 and eb["hasta_s"] == 16
            assert ea["tomado_en"] == "2026-11-21T18:00:00+00:00" and ea["ruido"]["nivel"] == "alto"
            assert ea["concluyente"]  # hubo aves aunque había ruido
            assert c.get(f"/audios/{ea['archivo']}").content[:4] == b"RIFF"
            assert sin_audio["aves"] is None
            assert malo["aves"]["error"] and malo["cuadros_analizados"] == 2  # el video se guarda igual
    finally:
        aves.detectar_crudo = original


def test_hexagono():
    """El mapa recibe solo conteos por hexágono; al tocar uno se piden sus fotos (solo las que cuentan) y aves."""
    from fastapi.testclient import TestClient
    import terreno.aves as aves
    from terreno.servidor import crear_app

    df = pd.read_parquet(DEMO)
    hx = solve_corridor(df)["hexes"][1]
    la, lo = h3.cell_to_latlng(hx)
    original = aves.detectar
    aves.detectar = lambda *a, **k: [{"cientifico": "Turdus falcklandii", "comun": "Austral Thrush",
                                      "confianza": 0.9, "inicio_s": 0, "fin_s": 3}]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            c = TestClient(crear_app(DEMO, Path(tmp), comunas=COMUNAS_DEMO))  # Claude simulado con con_claude
            foto = lambda: {"foto": ("f.jpg", jpeg((90, 90, 90)), "image/jpeg")}
            for o in (obs(True, "medio", fauna=[{"grupo": "abeja", "nombre": "", "cantidad": 2}]),
                      obs(True, "mucho"), obs(False, motivo="interior")):
                deshacer = con_claude(o)
                try:
                    c.post("/api/captura", data={"lat": la, "lon": lo}, files=foto())
                finally:
                    deshacer()
            c.post("/api/audio", data={"lat": la, "lon": lo}, files={"audio": ("a.wav", wav(), "audio/wav")})
            e = c.get("/api/estado").json()
            assert "capturas" not in e and "escuchas" not in e  # nada de listas completas en cada sondeo
            assert e["totales"] == {"capturas": 3, "cuentan": 2, "escuchas": 1}
            fila = next(f for f in filas(e) if f["h"] == hx)
            assert fila["fotos"] == 2 and fila["escuchas"] == 1
            assert sum(e["hex"]["fotos"]) == 2
            d = c.get(f"/api/hexagono/{hx}").json()
            assert d["n_fotos"] == 2 and len(d["fotos"]) == 2 and d["n_escuchas"] == 1
            assert d["fotos"][0]["medido_en"] >= d["fotos"][1]["medido_en"]  # lo más nuevo primero
            assert all("motivo_rechazo" not in f for f in d["fotos"])  # la descartada no se muestra
            assert d["especies"] == ["Turdus falcklandii"] and d["polinizadores"] == 2
            assert d["escuchas"][0]["detecciones"][0]["cientifico"] == "Turdus falcklandii"
            assert len(c.get(f"/api/hexagono/{hx}?n=1").json()["fotos"]) == 1
            vacio = c.get(f"/api/hexagono/{solve_corridor(df)['hexes'][3]}").json()
            assert vacio["n_fotos"] == 0 and vacio["fotos"] == [] and "especies" not in vacio
            assert c.get("/api/hexagono/no-es-un-hexagono").status_code == 404
            todo = c.get("/api/capturas").json()
            assert len(todo["capturas"]) == 3 and len(todo["escuchas"]) == 1
    finally:
        aves.detectar = original


def test_aves_wav():
    """leer_wav acepta lo que arma la página y rechaza lo demás (sin cargar BirdNET)."""
    import terreno.aves as aves
    x, tasa = aves.leer_wav(wav(1.5, 48000))
    assert tasa == 48000 and len(x) == 72000 and x.dtype == np.float32 and np.abs(x).max() <= 1
    for malo in (b"", b"RIFF1234WAVE", jpeg((1, 2, 3))):
        try:
            aves.leer_wav(malo)
        except ValueError:
            continue
        raise AssertionError("debió rechazar")


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("OK", nombre)


def test_sesiones_por_navegador():
    """Cada navegador (`s`) tiene su área y sus pesos; no se pisan entre sí ni tocan la sesión compartida."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(GS, Path(tmp), usar_claude=False, comunas=["Cerro Navia", "Quinta Normal"]))
        a, b = "navegadorAAAA", "navegadorBBBB"
        assert c.post(f"/api/seleccion?s={a}", json={"comunas": ["Cerro Navia"], "w_calor": 0.9, "w_arbol": 0.05, "w_personas": 0.05}).status_code == 200
        ea, eb, comun = (c.get(f"/api/estado{q}").json() for q in (f"?s={a}", f"?s={b}", ""))
        assert ea["seleccion"] == ["Cerro Navia"] and ea["parametros"]["w_calor"] == 0.9
        assert eb["seleccion"] == ["Cerro Navia", "Quinta Normal"] and eb["parametros"]["w_calor"] == 0.4
        assert comun["seleccion"] == ["Cerro Navia", "Quinta Normal"] and comun["parametros"]["w_calor"] == 0.4
        assert ea["sel_id"] != eb["sel_id"]
        # Un navegador nuevo (recargar la página) parte con los valores por defecto.
        assert c.get("/api/comunas?s=navegadorCCCC").json()["parametros"]["w_calor"] == 0.4
        assert c.get("/api/version?s=mal").status_code == 422


def test_comunas_vecinas():
    """Con «vecinas», el corredor de una comuna sin parques puede usar los de las comunas de al lado."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(GS, Path(tmp), usar_claude=False, comunas=["Independencia"]))
        e = c.get("/api/estado").json()
        assert e["ahora"]["hexes"] == 0 and e["parametros"]["vecinas"] is False and e["fuera"] == []
        u = e["hex"]["u"]
        assert c.post("/api/seleccion", json={"vecinas": True}).status_code == 200
        e = c.get("/api/estado").json()
        assert e["parametros"]["vecinas"] is True and e["ahora"]["hexes"] > 0
        dentro = sum(e["hex"]["ahora"])
        assert dentro + len(e["fuera"]) == e["ahora"]["hexes"] and 2 * dentro >= e["ahora"]["hexes"]
        assert all(f["comuna"] != "Independencia" for f in e["fuera"])
        assert e["hex"]["u"] == u                      # la urgencia de lo elegido no cambia
        assert len(e["hex"]["h"]) == len(u)            # ni el área que se muestra
        # Sin corredor con el presupuesto dado: el servidor dice cuánto falta.
        c.post("/api/seleccion", json={"comunas": ["Lo Prado"]})
        e = c.get("/api/estado").json()
        assert e["ahora"]["hexes"] == 0 and e["ahora"]["km_min"] > 3
        c.post("/api/seleccion", json={"km": e["ahora"]["km_min"] + 0.4})
        assert c.get("/api/estado").json()["ahora"]["hexes"] > 0


def test_perfiles_de_corredor():
    """El corredor se puede trazar para personas, aves, abejas o mixto; cada navegador guarda su perfil."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(GS, Path(tmp), usar_claude=False, comunas=["Santiago", "Providencia", "Ñuñoa"]))
        s = "navegadorPERF"
        base = c.get(f"/api/estado?s={s}").json()
        assert base["parametros"]["perfil"] == "humanos" and base["ahora"]["checkpoints"] == 0
        vistos = {}
        for perfil in ("fauna_aves", "fauna_abejas", "mixto"):
            assert c.post(f"/api/seleccion?s={s}", json={"perfil": perfil}).status_code == 200
            e = c.get(f"/api/estado?s={s}").json()
            assert e["parametros"]["perfil"] == perfil and e["ahora"]["hexes"] > 0
            assert sum(e["hex"]["checkpoint"]) == e["ahora"]["checkpoints"]
            vistos[perfil] = e["ahora"]
        assert vistos["fauna_aves"]["checkpoints"] == 0 and vistos["fauna_abejas"]["checkpoints"] > 0
        assert vistos["mixto"]["checkpoints"] > 0
        assert c.post(f"/api/seleccion?s={s}", json={"perfil": "dragones"}).status_code == 422
        assert c.get("/api/estado").json()["parametros"]["perfil"] == "humanos"   # la sesión compartida no cambió
        assert c.post(f"/api/seleccion?s={s}", json={"perfil": "humanos"}).status_code == 200
        assert c.get(f"/api/estado?s={s}").json()["ahora"]["personas_cubiertas"] == base["ahora"]["personas_cubiertas"]


def test_especies_combinadas():
    """Se puede elegir más de una especie: el criterio promedia el de cada una y la forma sale de quiénes son."""
    from fastapi.testclient import TestClient
    from ecologia import criterio_por_especies
    from terreno.servidor import crear_app

    df = pd.read_parquet(GS)
    sub = df[df["comuna"].isin(["Santiago", "Providencia", "Ñuñoa"])]
    solo = {e: criterio_por_especies(sub, [e]) for e in ("humanos", "aves", "abejas")}
    for combo in (["humanos", "abejas"], ["humanos", "aves"], ["aves", "abejas"], ["humanos", "aves", "abejas"]):
        prioridad, costo, _, _ = criterio_por_especies(sub, combo)
        assert np.allclose(prioridad, sum(solo[e][0] for e in combo) / len(combo))   # promedio simple de prioridades
        assert np.allclose(costo, (sum(solo[e][1] for e in combo) / len(combo)).clip(lower=0.01))
        assert prioridad.between(0, 1).all()

    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(GS, Path(tmp), usar_claude=False, comunas=["Santiago", "Providencia", "Ñuñoa"]))
        s = "navegadorESPE"
        assert c.get(f"/api/estado?s={s}").json()["parametros"]["especies"] == ["humanos"]
        for combo, islas in ((["aves", "humanos"], False), (["humanos", "abejas"], True), (["abejas", "aves"], True),
                             (["humanos", "aves", "abejas"], True)):
            assert c.post(f"/api/seleccion?s={s}", json={"especies": combo}).status_code == 200
            e = c.get(f"/api/estado?s={s}").json()
            assert e["parametros"]["especies"] == [x for x in ("humanos", "aves", "abejas") if x in combo]   # orden fijo
            assert e["ahora"]["hexes"] > 0 and e["ahora"]["km"] <= 3.0 + 1e-6      # corredor continuo dentro del presupuesto
            assert (e["ahora"]["checkpoints"] > 0) == islas                         # mini islas solo con abejas
            assert all(a or not cp for a, cp in zip(e["hex"]["ahora"], e["hex"]["checkpoint"]))   # las islas van sobre el corredor
        assert c.post(f"/api/seleccion?s={s}", json={"especies": []}).status_code == 422
        assert c.post(f"/api/seleccion?s={s}", json={"especies": ["gatos"]}).status_code == 422
        # La forma antigua sigue funcionando: «mixto» equivale a las tres especies.
        c.post(f"/api/seleccion?s={s}", json={"perfil": "mixto"})
        assert c.get(f"/api/estado?s={s}").json()["parametros"]["especies"] == ["humanos", "aves", "abejas"]


def test_vecinas_con_especies():
    """«Comunas vecinas» vale para cualquier combinación de especies, no solo para humanos."""
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(GS, Path(tmp), usar_claude=False, comunas=["Independencia"]))
        s = "navegadorVECI"
        for combo in (["aves"], ["abejas"], ["humanos", "aves"], ["humanos", "aves", "abejas"]):
            c.post(f"/api/seleccion?s={s}", json={"especies": combo, "vecinas": False, "km": 6})
            sin = c.get(f"/api/estado?s={s}").json()
            assert sin["ahora"]["hexes"] == 0 and sin["fuera"] == []        # Independencia sola no tiene dos parques que unir
            u = sin["hex"]["u"]
            c.post(f"/api/seleccion?s={s}", json={"vecinas": True})
            con = c.get(f"/api/estado?s={s}").json()
            dentro = sum(con["hex"]["ahora"])
            assert con["ahora"]["hexes"] > 0 and len(con["fuera"]) > 0, combo
            assert dentro + len(con["fuera"]) == con["ahora"]["hexes"] and 2 * dentro >= con["ahora"]["hexes"] - 1
            assert all(f["comuna"] != "Independencia" for f in con["fuera"])
            assert con["hex"]["u"] == u                                      # el color de lo elegido no cambia
