"""Caché con TTL, a mano, en memoria (D32), y la cabecera Cache-Status (D33).

Un diccionario y `time.monotonic()`: el reloj monotónico no salta si alguien cambia la
hora del sistema, así que una entrada nunca vence antes ni después de su TTL. Hay una
caché por tipo de dato: ciudades (búsqueda y ficha, 24 h) y pronóstico (15 min). Los
sensores no se cachean (D32).

Cada uso de la caché deja una entrada de Cache-Status según la RFC 9211:

    agregador-ciudades; hit; ttl=842          estaba y no había vencido
    agregador-ciudades; fwd=uri-miss; stored  no estaba: se fue a Open-Meteo y se guardó
    agregador-ciudades; fwd=stale; stored     estaba vencida
    agregador-ciudades; fwd=request; stored   la petición pidió Cache-Control: no-cache
"""

import math
import time
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import Any

from starlette.datastructures import Headers

from agregador.metricas import RegistroMetricas

Reloj = Callable[[], float]


@dataclass
class _Entrada:
    valor: Any
    vence: float


class CacheTTL:
    """Una caché con un TTL fijo para todas sus entradas."""

    def __init__(self, nombre: str, ttl: float, reloj: Reloj = time.monotonic):
        self.nombre = nombre  # el identificador en Cache-Status (detalle 7 del canvas)
        self.ttl = ttl
        self._reloj = reloj
        self._entradas: dict[Hashable, _Entrada] = {}

    def buscar(self, clave: Hashable) -> tuple[Any, str]:
        """Devuelve (valor, «hit») si está vigente; (None, «uri-miss» o «stale») si no."""
        entrada = self._entradas.get(clave)
        if entrada is None:
            return None, "uri-miss"
        if self._reloj() >= entrada.vence:
            # Vencida: se borra, y la respuesta nueva la reemplaza al guardarse.
            del self._entradas[clave]
            return None, "stale"
        return entrada.valor, "hit"

    def guardar(self, clave: Hashable, valor: Any) -> None:
        self._entradas[clave] = _Entrada(valor, self._reloj() + self.ttl)

    def ttl_restante(self, clave: Hashable) -> int:
        """Segundos de vida que le quedan a una entrada, redondeados hacia arriba."""
        entrada = self._entradas.get(clave)
        return max(0, math.ceil(entrada.vence - self._reloj())) if entrada else 0

    def __len__(self) -> int:
        return len(self._entradas)


def pide_no_cache(cabeceras: Headers) -> bool:
    """¿La petición trae `Cache-Control: no-cache`? (D33). La cabecera es una lista
    separada por comas y sin distinción de mayúsculas, p. ej. «max-age=0, No-Cache»."""
    directivas = cabeceras.get("cache-control", "")
    return any(parte.split("=")[0].strip().lower() == "no-cache" for parte in directivas.split(","))


async def con_cache(
    cache: CacheTTL,
    clave: Hashable,
    producir: Callable[[], Awaitable[Any]],
    *,
    saltar: bool,
    metricas: RegistroMetricas | None = None,
) -> tuple[Any, str]:
    """El valor desde la caché o desde `producir()`, y su entrada de Cache-Status.

    Con `saltar` (la petición pidió no-cache) nunca se responde desde la caché, pero el
    valor nuevo sí se guarda (D33). Si `producir()` falla, no se guarda nada y el error
    sigue hacia la ruta, que responde 502/504 (D20).
    """
    if saltar:
        motivo = "request"
    else:
        valor, estado = cache.buscar(clave)
        if estado == "hit":
            if metricas:
                metricas.registrar_cache(acierto=True)
            return valor, f"{cache.nombre}; hit; ttl={cache.ttl_restante(clave)}"
        motivo = estado

    if metricas:
        metricas.registrar_cache(acierto=False)
    valor = await producir()
    cache.guardar(clave, valor)
    return valor, f"{cache.nombre}; fwd={motivo}; stored"
