"""Pruebas de la Parte E: el cliente del otro grupo y GET /v1/libros (D44–D48), sin red.

Un servidor falso responde como dice su contrato
(`requirements/parte-e/openapi-grupo-open-library.json`) y anota cada petición, con el
timeout de lectura que llevaba. Cada prueba dice qué regla demuestra.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from agregador.main import app
from agregador.resiliencia import Politica

CIEN_ANOS = {
    "obra": "Cien años de soledad",
    "autor": "Gabriel García Márquez",
    "clave_autor": "OL27363A",
    "nombre_personal_real": "García Márquez, Gabriel",
    "fecha_nacimiento": "1927-03-06",
}


class GrupoFalso:
    """Hace de la API del grupo de Open Library. Cada paso del guion es un código, un
    (código, cuerpo) o una excepción; sin guion, responde «Cien años de soledad»."""

    def __init__(self, *pasos) -> None:
        self.pasos = list(pasos)
        self.peticiones: list[httpx.Request] = []

    def timeouts(self) -> list[float]:
        return [peticion.extensions["timeout"]["read"] for peticion in self.peticiones]

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.peticiones.append(peticion)
        if not self.pasos:
            return httpx.Response(200, json=CIEN_ANOS)
        paso = self.pasos.pop(0)
        if isinstance(paso, Exception):
            raise paso
        if isinstance(paso, tuple):
            codigo, cuerpo = paso
            if isinstance(cuerpo, str):
                return httpx.Response(codigo, text=cuerpo, headers={"Content-Type": "text/html"})
            return httpx.Response(codigo, json=cuerpo)
        if paso == 200:
            return httpx.Response(200, json=CIEN_ANOS)
        return httpx.Response(paso, json={"detail": "falso"})


@pytest.fixture
def api():
    with TestClient(app) as cliente:
        yield cliente


def con_grupo(api: TestClient, *pasos, base: float = 0.001) -> GrupoFalso:
    """Pone el servidor falso detrás de la app, con backoff de milisegundos pero con
    los timeouts de D50 tal como salen de la configuración."""
    falso = GrupoFalso(*pasos)
    estado = api.app.state
    estado.cliente_otro_grupo = httpx.AsyncClient(transport=httpx.MockTransport(falso), base_url="https://grupo.falso")
    politica = estado.politica_otro_grupo
    estado.politica_otro_grupo = Politica(
        dependencia=politica.dependencia,
        etiqueta=politica.etiqueta,
        maximo=politica.maximo,
        timeouts_lectura=politica.timeouts_lectura,
        timeout_conexion=politica.timeout_conexion,
        base=base,
        tope=base,
    )
    return falso


def libros(api: TestClient, titulo: str = "Cien años de soledad", **kwargs):
    return api.get("/v1/libros", params={"titulo": titulo}, **kwargs)


# Lo que responden ─────────────────────────────────────────────────────────────────


def test_responde_la_obra_con_sus_mismos_campos(api):
    """D45: los cinco campos de su ResumenObra, con sus nombres."""
    falso = con_grupo(api)
    respuesta = libros(api)
    assert (respuesta.status_code, respuesta.json()) == (200, CIEN_ANOS)
    assert falso.peticiones[0].url.path == "/v1/libros"
    assert falso.peticiones[0].url.params["titulo"] == "Cien años de soledad"


def test_los_campos_opcionales_pueden_faltar(api):
    """Su contrato solo exige obra, autor y clave_autor."""
    con_grupo(api, (200, {"obra": "X", "autor": "Y", "clave_autor": "OL1A"}))
    cuerpo = libros(api).json()
    assert (cuerpo["nombre_personal_real"], cuerpo["fecha_nacimiento"]) == (None, None)


def test_su_404_es_nuestro_404_sin_reintentar(api):
    """Su contrato: 404 «No se encontró una obra con autor». Es definitivo (D12)."""
    falso = con_grupo(api, 404)
    assert libros(api, "xqzwvt").status_code == 404
    assert len(falso.peticiones) == 1


def test_un_503_se_reintenta(api):
    """D50: las reglas de reintento selectivo de D12."""
    falso = con_grupo(api, 503, 200)
    assert libros(api).status_code == 200
    assert len(falso.peticiones) == 2


def test_dos_503_dan_502(api):
    """D50: máximo 2 intentos; después, 502 (D20)."""
    falso = con_grupo(api, 503, 503, 503)
    respuesta = libros(api)
    assert respuesta.status_code == 502
    assert respuesta.json() | {"detalle": ""} == {"detalle": "", "dependencia": "otro_grupo", "causa": "503", "intentos": 2}
    assert len(falso.peticiones) == 2


def test_dos_timeouts_de_10_segundos_dan_504(api):
    """D50: 2 intentos de hasta 10 s cada uno, y al agotarlos, 504."""
    falso = con_grupo(api, *[httpx.ReadTimeout("lenta")] * 2)
    respuesta = libros(api)
    assert (respuesta.status_code, respuesta.json()["causa"]) == (504, "timeout")
    assert falso.timeouts() == [10, 10]


@pytest.mark.parametrize("codigo", [502, 504])
def test_su_502_o_504_es_nuestro_502_sin_reintentar(api, codigo):
    """Si a ellos les falló Open Library, sí nos respondieron: para nosotros es 502 (D20).
    Nuestro 504 queda para cuando ellos no responden a tiempo."""
    falso = con_grupo(api, codigo)
    respuesta = libros(api)
    assert (respuesta.status_code, respuesta.json()["causa"]) == (502, str(codigo))
    assert len(falso.peticiones) == 1


def test_la_pagina_html_de_cloudflare_da_502(api):
    """Si su túnel responde una página HTML con 200, no cumple su contrato: 502."""
    con_grupo(api, (200, "<!DOCTYPE html><title>trycloudflare.com</title>"))
    respuesta = libros(api)
    assert (respuesta.status_code, respuesta.json()["causa"]) == (502, "respuesta_invalida")


def test_un_cuerpo_sin_los_campos_obligatorios_da_502(api):
    con_grupo(api, (200, {"obra": "Sin autor"}))
    assert libros(api).json()["causa"] == "respuesta_invalida"


def test_su_servidor_caido_da_502_y_lo_demas_sigue(api):
    """Salvaguarda 6: si su túnel no está, solo falla /v1/libros."""
    con_grupo(api, *[httpx.ConnectError("caído")] * 2)
    respuesta = libros(api)
    assert (respuesta.status_code, respuesta.json()["causa"]) == (502, "conexion")
    assert api.get("/salud").status_code == 200
    assert api.get("/v1/alertas").status_code == 200


# Validación y caché ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("titulo", ["", "   ", "x" * 201], ids=["vacio", "solo-espacios", "muy-largo"])
def test_titulo_invalido_da_422_sin_llamarlos(api, titulo):
    """Salvaguarda 3: validar antes de gastar una llamada a su API."""
    falso = con_grupo(api)
    assert libros(api, titulo).status_code == 422
    assert falso.peticiones == []


def test_la_segunda_vez_sale_de_la_cache(api):
    """D51: 10 min; sin distinguir mayúsculas ni espacios de los extremos."""
    falso = con_grupo(api)
    primera = libros(api)
    assert primera.headers["Cache-Status"] == "agregador-libros; fwd=uri-miss; stored"
    segunda = libros(api, "  cien AÑOS de soledad ")
    assert segunda.headers["Cache-Status"] == "agregador-libros; hit; ttl=600"
    assert segunda.json() == primera.json()
    assert len(falso.peticiones) == 1


def test_no_cache_vuelve_a_preguntarles(api):
    falso = con_grupo(api)
    libros(api)
    respuesta = libros(api, headers={"Cache-Control": "no-cache"})
    assert respuesta.headers["Cache-Status"] == "agregador-libros; fwd=request; stored"
    assert len(falso.peticiones) == 2


def test_un_404_no_se_guarda_en_la_cache(api):
    falso = con_grupo(api, 404, 200)
    assert libros(api).status_code == 404
    assert libros(api).status_code == 200
    assert len(falso.peticiones) == 2


def test_las_metricas_cuentan_al_otro_grupo(api):
    """D35: el otro grupo aparece como una dependencia más."""
    con_grupo(api, 503, 200)
    libros(api)
    otro = api.get("/v1/metricas").json()["dependencias"]["otro_grupo"]
    assert (otro["llamadas"], otro["intentos"], otro["reintentos"]) == (1, 2, 1)


def test_la_ruta_aparece_en_el_contrato_openapi(api):
    """Parte B.4: /docs documenta 404, 422, 502 y 504, y Cache-Status."""
    respuestas = api.get("/openapi.json").json()["paths"]["/v1/libros"]["get"]["responses"]
    assert {"200", "404", "422", "502", "504"} <= respuestas.keys()
    assert "Cache-Status" in respuestas["200"]["headers"]
