"""Pruebas de GET /v1/sensores con un servicio falso (D15, D21, D20), sin red.

El servicio real falla al azar, así que estos casos no se pueden forzar contra él: aquí
cada servicio falso falla siempre de la misma forma. El backoff se achica por variable de
entorno para que las pruebas no esperen.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from agregador.main import app

PAGINAS = {
    None: {"sensores": [{"id": "S-001", "tipo": "temperatura", "ubicacion": "Edificio A"},
                        {"id": "S-002", "tipo": "humedad", "ubicacion": "Biblioteca"}],
           "siguiente": "c2"},
    "c2": {"sensores": [{"id": "S-003", "tipo": "co2", "ubicacion": "Auditorio"}], "siguiente": None},
}


def lectura(sensor_id: str) -> dict:
    return {"sensor_id": sensor_id, "tipo": "temperatura", "valor": 24.3, "unidad": "°C",
            "marca_tiempo": "2026-10-23T17:00:00+00:00"}


def servicio(falla=lambda ruta: None, paginas=PAGINAS):
    """Servicio falso: `falla(ruta)` devuelve un código o un error para esa ruta, o None."""

    def manejar(peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path + (f"?{peticion.url.query.decode()}" if peticion.url.query else "")
        error = falla(ruta)
        if isinstance(error, Exception):
            raise error
        if error:
            return httpx.Response(error, json={"detalle": "falla a propósito"})
        if peticion.url.path == "/sensores":
            return httpx.Response(200, json=paginas[peticion.url.params.get("cursor")])
        sensor_id = peticion.url.path.split("/")[2]
        return httpx.Response(200, json=lectura(sensor_id))

    return httpx.MockTransport(manejar)


@pytest.fixture
def pedir(monkeypatch):
    monkeypatch.setenv("BACKOFF_BASE_S", "0.001")
    monkeypatch.setenv("BACKOFF_TOPE_S", "0.001")

    def pedir(transporte: httpx.MockTransport) -> httpx.Response:
        with TestClient(app) as cliente:
            app.state.cliente_sensores = httpx.AsyncClient(transport=transporte, base_url="http://servicio")
            return cliente.get("/v1/sensores")

    return pedir


def test_todo_bien_responde_completo(pedir):
    respuesta = pedir(servicio())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["completo"] is True and cuerpo["motivo"] is None
    assert [s["id"] for s in cuerpo["sensores"]] == ["S-001", "S-002", "S-003"]
    assert all(s["lectura"]["valor"] == 24.3 for s in cuerpo["sensores"])


def test_una_lectura_que_no_llega_deja_la_respuesta_incompleta(pedir):
    respuesta = pedir(servicio(lambda ruta: 503 if ruta == "/sensores/S-002/lectura" else None))
    cuerpo = respuesta.json()
    assert respuesta.status_code == 200
    assert cuerpo["completo"] is False
    assert cuerpo["motivo"] == "1 de 3 sensores sin lectura"
    s2 = cuerpo["sensores"][1]
    assert s2["lectura"] is None and s2["motivo"] == "sin respuesta (503)"


def test_una_pagina_que_no_llega_corta_el_recorrido(pedir):
    respuesta = pedir(servicio(lambda ruta: 503 if ruta == "/sensores?cursor=c2" else None))
    cuerpo = respuesta.json()
    assert respuesta.status_code == 200
    assert cuerpo["completo"] is False
    assert cuerpo["motivo"] == "la página 2 no respondió (503)"
    assert [s["id"] for s in cuerpo["sensores"]] == ["S-001", "S-002"]


def test_sin_ningun_sensor_responde_502(pedir):
    respuesta = pedir(servicio(lambda ruta: 503 if ruta == "/sensores" else None))
    assert respuesta.status_code == 502
    assert respuesta.json()["dependencia"] == "servicio_inestable"
    assert respuesta.json()["causa"] == "503"
    assert respuesta.json()["intentos"] == 6


def test_sin_ninguna_lectura_responde_502(pedir):
    respuesta = pedir(servicio(lambda ruta: 503 if ruta.endswith("/lectura") else None))
    assert respuesta.status_code == 502
    assert "ninguna lectura" in respuesta.json()["detalle"]


def test_solo_timeouts_responde_504(pedir):
    respuesta = pedir(servicio(lambda ruta: httpx.ReadTimeout("lenta")))
    assert respuesta.status_code == 504
    assert respuesta.json()["causa"] == "timeout"


def test_un_cursor_repetido_no_deja_el_recorrido_dando_vueltas(pedir):
    en_bucle = {None: {**PAGINAS[None], "siguiente": "c2"}, "c2": {**PAGINAS["c2"], "siguiente": "c2"}}
    respuesta = pedir(servicio(paginas=en_bucle))
    assert respuesta.status_code == 200
    assert respuesta.json()["motivo"] == "el servicio repitió un cursor"


def test_un_404_de_lectura_no_se_reintenta(pedir):
    llamadas = []

    def falla(ruta):
        if ruta == "/sensores/S-003/lectura":
            llamadas.append(ruta)
            return 404
        return None

    respuesta = pedir(servicio(falla))
    assert respuesta.json()["sensores"][2]["motivo"] == "el sensor no existe (404)"
    assert len(llamadas) == 1
