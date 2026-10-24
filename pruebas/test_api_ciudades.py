"""Colección: búsqueda de ciudades y clima, contra el stack y Open-Meteo real (HU1, HU2).

Cada prueba es una petición o una cadena, y su docstring dice qué demuestra (D26).
Usa `Cache-Control: no-cache` donde hace falta un MISS, porque el agregador puede
traer en caché lo de una corrida anterior.
"""

BUCARAMANGA = 3688465


def test_buscar_un_nombre_ambiguo_devuelve_todos_los_candidatos(api):
    """HU1, D05: «San José» en Colombia trae varios, cada uno con su departamento."""
    respuesta = api.get("/v1/ciudades", params={"nombre": "San José", "pais": "CO"})
    assert respuesta.status_code == 200
    candidatos = respuesta.json()
    assert len(candidatos) > 1
    assert all(c["codigo_pais"] == "CO" for c in candidatos)
    assert len({c["departamento"] for c in candidatos}) > 1
    assert "Cache-Status" in respuesta.headers


def test_buscar_sin_coincidencias_es_200_con_lista_vacia(api):
    """D36: no hay ciudades con ese nombre, pero la búsqueda sí se hizo."""
    respuesta = api.get("/v1/ciudades", params={"nombre": "Xqzwvtkj"})
    assert (respuesta.status_code, respuesta.json()) == (200, [])


def test_buscar_con_parametros_invalidos_da_422(api):
    """HU1, E2: nombre de una letra y país que no es ISO-2."""
    assert api.get("/v1/ciudades", params={"nombre": "B"}).status_code == 422
    assert api.get("/v1/ciudades", params={"nombre": "Bogotá", "pais": "COL"}).status_code == 422


def test_buscar_y_despues_pedir_el_clima_del_elegido(api):
    """HU1 → HU2: el id de un candidato sirve para pedir su clima (D07)."""
    [bucaramanga, *_] = [
        c for c in api.get("/v1/ciudades", params={"nombre": "Bucaramanga", "pais": "CO"}).json()
        if c["departamento"] == "Santander"
    ]
    respuesta = api.get(f"/v1/ciudades/{bucaramanga['id']}/clima", params={"dias": 3})
    assert respuesta.status_code == 200
    clima = respuesta.json()
    assert clima["ciudad"]["id"] == bucaramanga["id"]
    assert clima["zona_horaria"] == "America/Bogota"
    assert set(clima["actual"]) == {"hora", "temperatura_c", "humedad_pct", "codigo_tiempo", "viento_kmh"}
    assert len(clima["dias"]) == 3
    assert all(d["minima_c"] <= d["maxima_c"] for d in clima["dias"] if d["minima_c"] is not None)


def test_la_segunda_peticion_sale_de_la_cache(api):
    """D32, D33: no-cache obliga a ir a Open-Meteo; la siguiente sale de la caché."""
    fria = api.get(f"/v1/ciudades/{BUCARAMANGA}/clima", headers={"Cache-Control": "no-cache"})
    assert fria.headers["Cache-Status"] == (
        "agregador-ciudades; fwd=request; stored, agregador-pronostico; fwd=request; stored"
    )
    caliente = api.get(f"/v1/ciudades/{BUCARAMANGA}/clima")
    assert "agregador-ciudades; hit" in caliente.headers["Cache-Status"]
    assert "agregador-pronostico; hit" in caliente.headers["Cache-Status"]
    assert caliente.json() == fria.json()


def test_clima_de_un_id_inexistente_da_404(api):
    """HU2, E6: Open-Meteo responde 400 «Location ID not found.»; nosotros, 404."""
    respuesta = api.get("/v1/ciudades/999999999/clima")
    assert respuesta.status_code == 404


def test_clima_con_dias_fuera_de_rango_da_422(api):
    """HU2, E9: 1 a 16 días, validado antes de llamar a Open-Meteo."""
    assert api.get(f"/v1/ciudades/{BUCARAMANGA}/clima", params={"dias": 17}).status_code == 422
    assert api.get(f"/v1/ciudades/{BUCARAMANGA}/clima", params={"dias": 0}).status_code == 422


def test_las_metricas_cuentan_la_cache_y_open_meteo(api):
    """D35: después de las pruebas anteriores hay llamadas a Open-Meteo y aciertos de caché."""
    api.get(f"/v1/ciudades/{BUCARAMANGA}/clima")
    metricas = api.get("/v1/metricas").json()
    assert metricas["dependencias"]["open_meteo"]["llamadas"] > 0
    assert metricas["cache"]["aciertos"] > 0
    assert "/v1/ciudades/{id}/clima" in metricas["latencia_ms"]
