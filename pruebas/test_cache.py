"""Pruebas unitarias de la caché (D32, D33), sin red ni esperas de verdad.

Un reloj falso avanza a mano para ver vencer las entradas. Cada prueba dice qué regla
demuestra.
"""

import asyncio

import pytest
from starlette.datastructures import Headers

from agregador.cache import CacheTTL, con_cache, pide_no_cache
from agregador.metricas import RegistroMetricas


class RelojFalso:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


class Origen:
    """Hace de Open-Meteo: cuenta cuántas veces se le pidió el dato."""

    def __init__(self) -> None:
        self.llamadas = 0

    async def __call__(self):
        self.llamadas += 1
        return f"dato {self.llamadas}"


def usar(cache, clave, origen, *, saltar=False, metricas=None):
    return asyncio.run(con_cache(cache, clave, origen, saltar=saltar, metricas=metricas))


@pytest.fixture
def reloj():
    return RelojFalso()


@pytest.fixture
def cache(reloj):
    return CacheTTL("agregador-pronostico", 900, reloj=reloj)


def test_la_primera_vez_va_al_origen_y_guarda(cache):
    """Sin entrada: fwd=uri-miss y queda guardada."""
    origen = Origen()
    assert usar(cache, "k", origen) == ("dato 1", "agregador-pronostico; fwd=uri-miss; stored")
    assert len(cache) == 1


def test_la_segunda_vez_sale_de_la_cache_con_su_ttl(cache, reloj):
    """Vigente: hit, sin llamar al origen, y ttl con los segundos que le quedan."""
    origen = Origen()
    usar(cache, "k", origen)
    reloj.ahora += 58
    assert usar(cache, "k", origen) == ("dato 1", "agregador-pronostico; hit; ttl=842")
    assert origen.llamadas == 1


def test_al_vencer_el_ttl_vuelve_al_origen(cache, reloj):
    """Vencida justo a los 900 s: fwd=stale, y se reemplaza por el dato nuevo."""
    origen = Origen()
    usar(cache, "k", origen)
    reloj.ahora += 899.9
    assert usar(cache, "k", origen)[1].startswith("agregador-pronostico; hit")
    reloj.ahora += 0.1
    assert usar(cache, "k", origen) == ("dato 2", "agregador-pronostico; fwd=stale; stored")
    assert usar(cache, "k", origen) == ("dato 2", "agregador-pronostico; hit; ttl=900")


def test_no_cache_nunca_responde_desde_la_cache_pero_guarda(cache):
    """Salvaguarda 10: con no-cache se va al origen aunque haya una entrada vigente,
    y la respuesta nueva queda para las siguientes (D33)."""
    origen = Origen()
    usar(cache, "k", origen)
    assert usar(cache, "k", origen, saltar=True) == ("dato 2", "agregador-pronostico; fwd=request; stored")
    assert usar(cache, "k", origen) == ("dato 2", "agregador-pronostico; hit; ttl=900")


def test_las_claves_no_se_mezclan(cache):
    """Otra ciudad u otros días son otra entrada."""
    origen = Origen()
    usar(cache, ("pronostico", 1, 7), origen)
    assert usar(cache, ("pronostico", 1, 3), origen)[1].endswith("fwd=uri-miss; stored")
    assert usar(cache, ("pronostico", 2, 7), origen)[1].endswith("fwd=uri-miss; stored")
    assert origen.llamadas == 3


def test_si_el_origen_falla_no_se_guarda_nada(cache):
    """Un 502/504 no se cachea: la siguiente petición vuelve a intentar."""

    async def falla():
        raise RuntimeError("Open-Meteo caído")

    with pytest.raises(RuntimeError):
        usar(cache, "k", falla)
    assert len(cache) == 0


def test_cuenta_aciertos_y_fallos_en_las_metricas(cache):
    """D35: hit suma un acierto; uri-miss, stale y no-cache suman un fallo."""
    metricas = RegistroMetricas()
    origen = Origen()
    usar(cache, "k", origen, metricas=metricas)
    usar(cache, "k", origen, metricas=metricas)
    usar(cache, "k", origen, saltar=True, metricas=metricas)
    assert metricas.instantanea()["cache"] == {"aciertos": 1, "fallos": 2}


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("no-cache", True),
        ("No-Cache", True),
        ("max-age=0, no-cache", True),
        ('no-cache="set-cookie"', True),
        ("max-age=0", False),
        ("no-store", False),
        (None, False),
    ],
)
def test_reconoce_la_directiva_no_cache(valor, esperado):
    cabeceras = Headers({"cache-control": valor} if valor else {})
    assert pide_no_cache(cabeceras) is esperado
