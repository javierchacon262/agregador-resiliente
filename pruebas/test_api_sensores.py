"""Colección: salud, sensores y métricas contra el stack levantado (D26).

El servicio inestable falla al azar, así que estas pruebas no esperan un resultado
exacto: comprueban lo que tiene que cumplirse siempre, con cualquier parámetro del
docente.
"""

import time

import pytest

PLAZO_SENSORES_S = 45  # D18


def test_salud(api):
    """GET /salud responde sin consultar las dependencias (HU5)."""
    respuesta = api.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok"}


@pytest.fixture(scope="module")
def sensores(api):
    """Una llamada a /v1/sensores, compartida por las pruebas que la revisan."""
    inicio = time.monotonic()
    respuesta = api.get("/v1/sensores")
    return respuesta, time.monotonic() - inicio


def test_sensores_responde_dentro_del_plazo(sensores):
    """Nunca pasa de 45 s, aunque el servicio esté lento (D18)."""
    _, duracion = sensores
    assert duracion < PLAZO_SENSORES_S + 2


def test_sensores_nunca_responde_500(sensores):
    """200 con lo obtenido, o 502/504 si no obtuvo nada: nunca 500 (D20, D21)."""
    respuesta, _ = sensores
    assert respuesta.status_code in (200, 502, 504)


def test_sensores_es_coherente(sensores):
    """Si dice completo, todos tienen lectura; si no, dice por qué (D15)."""
    respuesta, _ = sensores
    if respuesta.status_code != 200:
        cuerpo = respuesta.json()
        assert cuerpo["dependencia"] == "servicio_inestable"
        assert cuerpo["causa"] and cuerpo["intentos"] >= 1
        return
    cuerpo = respuesta.json()
    assert cuerpo["sensores"], "un 200 trae al menos un sensor con lectura (D21)"
    assert any(s["lectura"] for s in cuerpo["sensores"])
    for sensor in cuerpo["sensores"]:
        assert sensor["id"] and sensor["tipo"] and sensor["ubicacion"]
        assert (sensor["lectura"] is None) == (sensor["motivo"] is not None)
    if cuerpo["completo"]:
        assert cuerpo["motivo"] is None
        assert all(s["lectura"] for s in cuerpo["sensores"])
    else:
        assert cuerpo["motivo"]


def test_las_metricas_cuentan_los_intentos(api, sensores):
    """Después de pedir sensores, /v1/metricas muestra los intentos al servicio (D35)."""
    metricas = api.get("/v1/metricas").json()
    servicio = metricas["dependencias"]["servicio_inestable"]
    assert servicio["intentos"] >= servicio["llamadas"] >= 1
    assert servicio["reintentos"] == servicio["intentos"] - servicio["llamadas"]
    assert "/v1/sensores" in metricas["latencia_ms"]
