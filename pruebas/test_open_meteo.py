"""Pruebas unitarias del cliente de Open-Meteo (tarea 10; D22, E1, E6, E7), sin red.

Las llamadas pasan por los reintentos de verdad, con un backoff de milisegundos para
que las pruebas no esperen. Cada prueba dice qué regla demuestra.
"""

import asyncio
import time
from datetime import date

import httpx
import pytest

from agregador.clientes import open_meteo
from agregador.resiliencia import ErrorDependencia, Politica
from open_meteo_falso import BUCARAMANGA, PRONOSTICO, OpenMeteoFalso

POLITICA = Politica(
    dependencia="open_meteo",
    etiqueta="open-meteo",
    maximo=3,  # D22
    timeouts_lectura=(3, 6, 8),
    timeout_conexion=2,
    base=0.001,
    tope=0.001,
)


def correr(falso: OpenMeteoFalso, funcion, *args):
    async def dentro():
        async with falso.cliente("https://open-meteo.falso") as cliente:
            fecha_limite = time.monotonic() + 15
            return await funcion(cliente, *args, politica=POLITICA, fecha_limite=fecha_limite)

    return asyncio.run(dentro())


def ciudad():
    return open_meteo._CiudadExterna.model_validate(BUCARAMANGA).a_ciudad()


# Búsqueda ────────────────────────────────────────────────────────────────────────


def test_busqueda_convierte_a_nuestros_nombres():
    falso = OpenMeteoFalso()
    [candidato] = correr(falso, open_meteo.buscar, "Bucaramanga", None)
    assert candidato.model_dump() == {
        "id": 3688465,
        "nombre": "Bucaramanga",
        "departamento": "Santander",
        "pais": "Colombia",
        "codigo_pais": "CO",
        "latitud": 7.125,
        "longitud": -73.11895,
        "poblacion": 581130,
    }


def test_busqueda_pide_en_espanol_y_filtra_por_pais():
    falso = OpenMeteoFalso()
    correr(falso, open_meteo.buscar, "San José", "CO")
    params = falso.peticiones[0].url.params
    assert (params["language"], params["countryCode"], params["count"]) == ("es", "CO", "10")


def test_busqueda_sin_results_es_lista_vacia():
    """E1: sin coincidencias Open-Meteo responde 200 y omite `results` → [] (D36)."""
    assert correr(OpenMeteoFalso(), open_meteo.buscar, "Xqzwvt", None) == []


def test_busqueda_con_503_se_reintenta():
    """D22: los mismos reintentos selectivos que con los sensores."""
    falso = OpenMeteoFalso(search=[503, httpx.ConnectError("caída")])
    assert len(correr(falso, open_meteo.buscar, "Bucaramanga", None)) == 1
    assert len(falso.peticiones) == 3


def test_busqueda_con_tres_503_da_502():
    """D22: máximo 3 intentos hacia Open-Meteo; después, 502 (D20)."""
    falso = OpenMeteoFalso(search=[503, 503, 503, 503])
    with pytest.raises(ErrorDependencia) as error:
        correr(falso, open_meteo.buscar, "Bucaramanga", None)
    assert (error.value.codigo, error.value.causa, error.value.intentos) == (502, "503", 3)
    assert len(falso.peticiones) == 3


def test_busqueda_con_timeouts_da_504():
    falso = OpenMeteoFalso(search=[httpx.ReadTimeout("lenta")] * 3)
    with pytest.raises(ErrorDependencia) as error:
        correr(falso, open_meteo.buscar, "Bucaramanga", None)
    assert (error.value.codigo, error.value.causa) == (504, "timeout")


def test_un_429_de_open_meteo_se_reintenta_sin_compuerta():
    """D22: Open-Meteo no usa la compuerta; el 429 se reintenta con backoff."""
    falso = OpenMeteoFalso(search=[429])
    assert len(correr(falso, open_meteo.buscar, "Bucaramanga", None)) == 1


def test_un_400_de_la_busqueda_no_se_reintenta_y_da_502():
    """Salvaguarda 1: ni los 400 de Open-Meteo se reintentan. En la búsqueda un 400 es
    un error nuestro, no del usuario (validamos antes), así que es 502."""
    falso = OpenMeteoFalso(search=[(400, {"error": True, "reason": "Parameter count must be between 1 and 100"})])
    with pytest.raises(ErrorDependencia) as error:
        correr(falso, open_meteo.buscar, "Bucaramanga", None)
    assert (error.value.codigo, error.value.causa) == (502, "400")
    assert "Parameter count" in error.value.detalle
    assert len(falso.peticiones) == 1


def test_busqueda_que_no_cumple_el_modelo_da_502():
    falso = OpenMeteoFalso(search=[(200, {"results": [{"id": "no es un número", "name": "X"}]})])
    with pytest.raises(ErrorDependencia) as error:
        correr(falso, open_meteo.buscar, "Bucaramanga", None)
    assert (error.value.codigo, error.value.causa) == (502, "respuesta_invalida")


# Ficha por id ────────────────────────────────────────────────────────────────────


def test_ficha_de_una_ciudad_por_id():
    assert correr(OpenMeteoFalso(), open_meteo.obtener_ciudad, 3688465).nombre == "Bucaramanga"


def test_id_inexistente_es_none_sin_reintentar():
    """E6: «Location ID not found.» llega como 400; no se reintenta y la ruta da 404."""
    falso = OpenMeteoFalso(get=[(400, {"reason": "Location ID not found.", "error": True})])
    assert correr(falso, open_meteo.obtener_ciudad, 999999999) is None
    assert len(falso.peticiones) == 1


def test_otro_400_de_la_ficha_no_es_404():
    """E6: no todo 400 de Open-Meteo es «no existe»; los demás son 502."""
    falso = OpenMeteoFalso(get=[(400, {"reason": "Invalid parameter", "error": True})])
    with pytest.raises(ErrorDependencia) as error:
        correr(falso, open_meteo.obtener_ciudad, 3688465)
    assert error.value.codigo == 502


# Pronóstico ──────────────────────────────────────────────────────────────────────


def test_pronostico_junta_las_listas_paralelas_por_dia():
    """E7: de daily.time[], daily.temperature_2m_max[]… a una lista de días."""
    zona, actual, dias = correr(OpenMeteoFalso(), open_meteo.pronosticar, ciudad(), 3)
    assert zona == "America/Bogota"
    assert (actual.temperatura_c, actual.humedad_pct, actual.codigo_tiempo, actual.viento_kmh) == (28.6, 57, 3, 7.5)
    assert [(d.fecha, d.maxima_c, d.minima_c, d.prob_lluvia_pct) for d in dias] == [
        (date(2026, 10, 23), 28.7, 21.0, 84),
        (date(2026, 10, 24), 26.7, 20.6, 96),
        (date(2026, 10, 25), 26.4, 20.3, None),  # un null de Open-Meteo sigue siendo null
    ]


def test_pronostico_pide_las_variables_del_canvas():
    """Detalle 8 del canvas: variables actuales y diarias, zona automática y días."""
    falso = OpenMeteoFalso()
    correr(falso, open_meteo.pronosticar, ciudad(), 5)
    params = falso.peticiones[0].url.params
    assert params["current"] == "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
    assert params["daily"] == "temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    assert (params["timezone"], params["forecast_days"]) == ("auto", "5")
    assert (params["latitude"], params["longitude"]) == ("7.125", "-73.11895")


def test_pronostico_con_listas_de_distinto_largo_da_502():
    """E7: si las listas no tienen el mismo largo no se adivina: 502, no datos a medias."""
    roto = PRONOSTICO | {"daily": PRONOSTICO["daily"] | {"temperature_2m_min": [21.0, 20.6]}}
    with pytest.raises(ErrorDependencia) as error:
        correr(OpenMeteoFalso(forecast=[(200, roto)]), open_meteo.pronosticar, ciudad(), 3)
    assert (error.value.codigo, error.value.causa) == (502, "respuesta_invalida")


def test_pronostico_sin_current_da_502():
    roto = {clave: valor for clave, valor in PRONOSTICO.items() if clave != "current"}
    with pytest.raises(ErrorDependencia) as error:
        correr(OpenMeteoFalso(forecast=[(200, roto)]), open_meteo.pronosticar, ciudad(), 3)
    assert error.value.codigo == 502
