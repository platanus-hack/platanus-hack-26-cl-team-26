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
        c = TestClient(crear_app(DEMO, Path(tmp)))
        for resultado, esperado in ((obs(False, "ninguno", "Interior"), "descartada"), (None, "sin_validar")):
            deshacer = con_claude(resultado)
            try:
                d = c.post("/api/captura", data=form, files=foto).json()
            finally:
                deshacer()
            assert d["validacion"] == esperado and not d["cuenta"] and not d["corredor_cambio"]
            assert d["ahora"]["verificados"] == 0
        assert not any(h["verificado"] for h in c.get("/api/estado").json()["hexes"])
        deshacer = con_claude(obs(True, "ninguno"))  # válida y sin espacio: sale del corredor
        try:
            d = c.post("/api/captura", data=form, files=foto).json()
        finally:
            deshacer()
        assert d["validacion"] == "valida" and d["cuenta"] and d["corredor_cambio"]
        e = c.get("/api/estado").json()
        assert [x["validacion"] for x in e["capturas"]] == ["descartada", "sin_validar", "valida"]
        assert any(h["verificado"] for h in e["hexes"])


def test_servidor():
    from fastapi.testclient import TestClient
    from terreno.servidor import crear_app

    df = pd.read_parquet(DEMO)
    hx = solve_corridor(df)["hexes"][0]
    lat, lon = h3.cell_to_latlng(hx)
    with tempfile.TemporaryDirectory() as tmp:
        c = TestClient(crear_app(DEMO, Path(tmp), clave="secreta", usar_claude=False, aceptar_sin_validar=True))
        assert c.get("/").status_code == 200 and c.get("/mapa").status_code == 200
        form = {"lat": str(lat), "lon": str(lon), "precision_m": "8"}
        foto = {"foto": ("c.jpg", jpeg((128, 128, 128)), "image/jpeg")}
        assert c.post("/api/captura", data=form, files=foto).status_code == 403
        r = c.post("/api/captura?k=secreta", data=form, files=foto)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["captura"]["h3_index"] == hx and not d["fuera_de_area"] and d["captura"]["fuente"] == "indice_verde"
        e = c.get("/api/estado").json()
        assert len(e["capturas"]) == 1 and any(h["verificado"] for h in e["hexes"])
        assert c.get(f"/fotos/{d['captura']['id']}_min.jpg").status_code == 200
        assert c.get("/fotos/..%2F..%2Fsecreto.jpg").status_code == 404
        assert (Path(tmp) / "terreno_h3.parquet").exists()
        r = c.post("/api/captura?k=secreta", data=form, files={"foto": ("x.jpg", b"no es imagen", "image/jpeg")})
        assert r.status_code == 422


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("OK", nombre)
