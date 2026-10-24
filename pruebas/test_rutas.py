"""Pruebas de las rutas de ciudades y alertas (tareas 12 y 13), sin red.

La app arranca de verdad con su lifespan, pero los clientes de Open-Meteo se cambian
por uno falso que anota cada petición. Así se ven los códigos de estado, las
cabeceras y cuántas llamadas se gastaron, sin depender de internet.
"""

import pytest
from fastapi.testclient import TestClient

from agregador.main import app
from agregador.resiliencia import Politica
from open_meteo_falso import OpenMeteoFalso

ALERTA = {"objetivo": {"tipo": "ciudad", "id": 3688465}, "variable": "temperatura", "condicion": "mayor_que", "umbral": 30}


@pytest.fixture
def api():
    with TestClient(app) as cliente:
        yield cliente


def con_open_meteo(api: TestClient, **guiones) -> OpenMeteoFalso:
    """Pone un Open-Meteo falso detrás de la app, con backoff de milisegundos."""
    falso = OpenMeteoFalso(**guiones)
    estado = api.app.state
    estado.cliente_geocoding = falso.cliente("https://geocoding.falso")
    estado.cliente_pronostico = falso.cliente("https://forecast.falso")
    estado.politica_open_meteo = Politica(
        dependencia="open_meteo", etiqueta="open-meteo", maximo=3, timeouts_lectura=(3, 6, 8),
        timeout_conexion=2, base=0.001, tope=0.001,
    )
    return falso


# HU1 · Buscar ────────────────────────────────────────────────────────────────────


def test_busqueda_devuelve_candidatos_y_cachea(api):
    falso = con_open_meteo(api)
    primera = api.get("/v1/ciudades", params={"nombre": "San José", "pais": "co"})
    assert primera.status_code == 200
    assert primera.json()[0]["departamento"] == "Nariño"
    assert primera.headers["Cache-Status"] == "agregador-ciudades; fwd=uri-miss; stored"
    # El país se normaliza a mayúsculas antes de llamar a Open-Meteo.
    assert falso.peticiones[0].url.params["countryCode"] == "CO"

    segunda = api.get("/v1/ciudades", params={"nombre": "san josé", "pais": "CO"})
    assert segunda.json() == primera.json()
    assert segunda.headers["Cache-Status"].startswith("agregador-ciudades; hit; ttl=")
    assert len(falso.peticiones) == 1


def test_busqueda_sin_coincidencias_es_200_con_lista_vacia(api):
    """D36: una búsqueda vacía no es un recurso inexistente."""
    con_open_meteo(api)
    respuesta = api.get("/v1/ciudades", params={"nombre": "Xqzwvt"})
    assert (respuesta.status_code, respuesta.json()) == (200, [])


@pytest.mark.parametrize(
    "params",
    [{"nombre": "B"}, {}, {"nombre": "Bogotá", "pais": "COL"}, {"nombre": "Bogotá", "pais": "1A"}],
    ids=["nombre-de-1-letra", "sin-nombre", "pais-de-3-letras", "pais-con-numero"],
)
def test_parametros_invalidos_dan_422_sin_llamar_a_open_meteo(api, params):
    """Salvaguarda 4 (E2): validar antes de gastar una llamada."""
    falso = con_open_meteo(api)
    assert api.get("/v1/ciudades", params=params).status_code == 422
    assert falso.peticiones == []


def test_open_meteo_caido_da_502_con_el_cuerpo_de_d20(api):
    con_open_meteo(api, search=[503, 503, 503])
    respuesta = api.get("/v1/ciudades", params={"nombre": "Bucaramanga"})
    assert respuesta.status_code == 502
    assert respuesta.json() == {
        "detalle": "Open-Meteo respondió 503 en 3 intentos",
        "dependencia": "open_meteo",
        "causa": "503",
        "intentos": 3,
    }


def test_un_fallo_no_queda_en_la_cache(api):
    """Después de un 502 la siguiente petición vuelve a intentar, y le va bien."""
    con_open_meteo(api, search=[503, 503, 503])
    assert api.get("/v1/ciudades", params={"nombre": "Bucaramanga"}).status_code == 502
    respuesta = api.get("/v1/ciudades", params={"nombre": "Bucaramanga"})
    assert respuesta.status_code == 200
    assert "fwd=uri-miss" in respuesta.headers["Cache-Status"]


# HU2 · Clima ─────────────────────────────────────────────────────────────────────


def test_clima_encadena_ficha_y_pronostico(api):
    """D07: dos llamadas distintas a Open-Meteo, en orden."""
    falso = con_open_meteo(api)
    respuesta = api.get("/v1/ciudades/3688465/clima", params={"dias": 3})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ciudad"]["nombre"] == "Bucaramanga"
    assert cuerpo["zona_horaria"] == "America/Bogota"
    assert cuerpo["actual"]["temperatura_c"] == 28.6
    assert [dia["fecha"] for dia in cuerpo["dias"]] == ["2026-10-23", "2026-10-24", "2026-10-25"]
    assert falso.rutas() == ["/v1/get", "/v1/forecast"]


def test_clima_trae_7_dias_por_defecto(api):
    """Detalle 2 del canvas."""
    falso = con_open_meteo(api)
    api.get("/v1/ciudades/3688465/clima")
    assert falso.peticiones[1].url.params["forecast_days"] == "7"


def test_clima_lleva_una_entrada_de_cache_status_por_cache(api):
    """D33: la ficha (24 h) y el pronóstico (15 min) en la misma cabecera."""
    falso = con_open_meteo(api)
    primera = api.get("/v1/ciudades/3688465/clima")
    assert primera.headers["Cache-Status"] == (
        "agregador-ciudades; fwd=uri-miss; stored, agregador-pronostico; fwd=uri-miss; stored"
    )
    segunda = api.get("/v1/ciudades/3688465/clima")
    assert segunda.headers["Cache-Status"] == "agregador-ciudades; hit; ttl=86400, agregador-pronostico; hit; ttl=900"
    assert len(falso.peticiones) == 2


def test_no_cache_va_a_open_meteo_aunque_haya_cache(api):
    """Salvaguarda 10: Cache-Control: no-cache nunca se responde desde la caché."""
    falso = con_open_meteo(api)
    api.get("/v1/ciudades/3688465/clima")
    respuesta = api.get("/v1/ciudades/3688465/clima", headers={"Cache-Control": "no-cache"})
    assert respuesta.headers["Cache-Status"] == (
        "agregador-ciudades; fwd=request; stored, agregador-pronostico; fwd=request; stored"
    )
    assert len(falso.peticiones) == 4


def test_otros_dias_son_otra_entrada_del_pronostico(api):
    con_open_meteo(api)
    api.get("/v1/ciudades/3688465/clima", params={"dias": 3})
    respuesta = api.get("/v1/ciudades/3688465/clima", params={"dias": 5})
    assert respuesta.headers["Cache-Status"].startswith("agregador-ciudades; hit")
    assert respuesta.headers["Cache-Status"].endswith("agregador-pronostico; fwd=uri-miss; stored")


def test_id_inexistente_da_404_sin_reintentar(api):
    """E6: el 400 «Location ID not found.» de Open-Meteo se traduce a 404."""
    falso = con_open_meteo(api, get=[(400, {"reason": "Location ID not found.", "error": True})])
    respuesta = api.get("/v1/ciudades/999999999/clima")
    assert respuesta.status_code == 404
    assert falso.rutas() == ["/v1/get"]


@pytest.mark.parametrize(
    "ruta", ["/v1/ciudades/3688465/clima?dias=0", "/v1/ciudades/3688465/clima?dias=17", "/v1/ciudades/abc/clima",
             "/v1/ciudades/0/clima"],
    ids=["0-dias", "17-dias", "id-no-numerico", "id-cero"],
)
def test_clima_con_parametros_invalidos_da_422_sin_llamar(api, ruta):
    """E8, E9: validamos el rango de días nosotros, sin confiar en Open-Meteo."""
    falso = con_open_meteo(api)
    assert api.get(ruta).status_code == 422
    assert falso.peticiones == []


def test_pronostico_invalido_da_502_y_no_datos_a_medias(api):
    con_open_meteo(api, forecast=[(200, {"timezone": "America/Bogota"})])
    respuesta = api.get("/v1/ciudades/3688465/clima")
    assert respuesta.status_code == 502
    assert respuesta.json()["causa"] == "respuesta_invalida"


def test_timeouts_de_open_meteo_dan_504(api):
    import httpx

    con_open_meteo(api, get=[httpx.ReadTimeout("lenta")] * 3)
    respuesta = api.get("/v1/ciudades/3688465/clima")
    assert (respuesta.status_code, respuesta.json()["causa"]) == (504, "timeout")


# HU4 · Alertas ───────────────────────────────────────────────────────────────────


def test_crear_alerta_da_201_con_location(api):
    respuesta = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": "k-1"})
    assert respuesta.status_code == 201
    alerta = respuesta.json()
    assert alerta["id"] == "a-0001"
    assert respuesta.headers["Location"] == "/v1/alertas/a-0001"
    assert api.get(respuesta.headers["Location"]).json() == alerta


def test_sin_idempotency_key_da_400(api):
    for cabeceras in ({}, {"Idempotency-Key": ""}, {"Idempotency-Key": "x" * 256}):
        assert api.post("/v1/alertas", json=ALERTA, headers=cabeceras).status_code == 400
    assert api.get("/v1/alertas").json() == []


def test_repetir_la_clave_devuelve_la_misma_respuesta_sin_duplicar(api):
    """Parte D.1 y D.2 del enunciado: dos peticiones iguales, una alerta."""
    primera = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": "k-1"})
    segunda = api.post("/v1/alertas", json=ALERTA | {"umbral": 30.0}, headers={"Idempotency-Key": "k-1"})
    assert (segunda.status_code, segunda.json()) == (primera.status_code, primera.json())
    assert segunda.headers["Location"] == primera.headers["Location"]
    assert len(api.get("/v1/alertas").json()) == 1


def test_otra_clave_crea_otra_alerta(api):
    api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": "k-1"})
    otra = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": "k-2"})
    assert otra.json()["id"] == "a-0002"


def test_misma_clave_con_otro_cuerpo_da_422(api):
    api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": "k-1"})
    respuesta = api.post("/v1/alertas", json=ALERTA | {"umbral": 35}, headers={"Idempotency-Key": "k-1"})
    assert respuesta.status_code == 422
    assert len(api.get("/v1/alertas").json()) == 1


@pytest.mark.parametrize(
    "cambio",
    [{"variable": "presion"}, {"condicion": "igual_a"}, {"umbral": "mucho"}, {"objetivo": {"tipo": "pais", "id": "CO"}},
     {"extra": 1}],
    ids=["variable", "condicion", "umbral", "objetivo", "campo-de-mas"],
)
def test_cuerpo_invalido_da_422_y_no_gasta_la_clave(api, cambio):
    assert api.post("/v1/alertas", json=ALERTA | cambio, headers={"Idempotency-Key": "k-1"}).status_code == 422
    # La clave no quedó registrada: con un cuerpo válido funciona.
    assert api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": "k-1"}).status_code == 201


def test_alerta_inexistente_da_404(api):
    assert api.get("/v1/alertas/a-0099").status_code == 404


def test_las_rutas_aparecen_en_el_contrato_openapi(api):
    """Parte B.4: /docs describe el contrato, incluidos los 502/504 y Cache-Status."""
    rutas = api.get("/openapi.json").json()["paths"]
    clima = rutas["/v1/ciudades/{id}/clima"]["get"]["responses"]
    assert {"200", "404", "422", "502", "504"} <= clima.keys()
    assert "Cache-Status" in clima["200"]["headers"]
    crear = rutas["/v1/alertas"]["post"]
    assert {"201", "400", "409", "422"} <= crear["responses"].keys()
    assert any(p["name"] == "Idempotency-Key" for p in crear["parameters"])
