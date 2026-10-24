"""Búsqueda de ciudades y clima por id (HU1, HU2; D05, D07).

Los parámetros se validan con FastAPI antes de gastar una llamada a Open-Meteo (422,
E2, E8). Las dos rutas usan la caché (D32) y dicen en `Cache-Status` de dónde salió
cada parte de la respuesta (D33).
"""

import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response

from agregador.cache import con_cache, pide_no_cache
from agregador.clientes import open_meteo
from agregador.modelos import Ciudad, CuerpoErrorDependencia, RespuestaClima

router = APIRouter(prefix="/v1", tags=["ciudades"])

ERRORES_OPEN_METEO = {
    502: {"model": CuerpoErrorDependencia, "description": "Open-Meteo falló o respondió algo que no cumple el modelo"},
    504: {"model": CuerpoErrorDependencia, "description": "Open-Meteo no respondió a tiempo o se agotó el plazo de 15 s"},
}
CABECERA_CACHE = {
    "Cache-Status": {
        "description": "RFC 9211: si la respuesta salió de la caché (hit) o de Open-Meteo (fwd) y por qué (D33)",
        "schema": {"type": "string"},
    }
}


def _fecha_limite(request: Request) -> float:
    # La fija la ruta al recibir la petición y la comparten todas sus llamadas (D18).
    return time.monotonic() + request.app.state.config.plazo_open_meteo_s


@router.get(
    "/ciudades",
    summary="Buscar ciudades por nombre, con su departamento y país",
    description=(
        "Devuelve todos los candidatos para que el usuario elija el correcto: «San José» trae diez, "
        "y el primero es de California (D05). Sin coincidencias, una lista vacía (D36). "
        "`Cache-Control: no-cache` se salta la caché de 24 h."
    ),
    responses={200: {"headers": CABECERA_CACHE}, **ERRORES_OPEN_METEO},
)
async def buscar_ciudades(
    request: Request,
    response: Response,
    nombre: Annotated[str, Query(min_length=2, max_length=100, description="Al menos 2 caracteres (E2)")],
    pais: Annotated[
        str | None, Query(pattern="^[A-Za-z]{2}$", description="Código ISO 3166-1 alfa-2 opcional, p. ej. CO (E4)")
    ] = None,
) -> list[Ciudad]:
    estado = request.app.state
    fecha_limite = _fecha_limite(request)
    nombre = nombre.strip()
    pais = pais.upper() if pais else None

    async def producir():
        return await open_meteo.buscar(
            estado.cliente_geocoding,
            nombre,
            pais,
            politica=estado.politica_open_meteo,
            fecha_limite=fecha_limite,
            metricas=estado.metricas,
        )

    # Open-Meteo no distingue mayúsculas al buscar, así que la clave tampoco.
    clave = ("buscar", nombre.casefold(), pais)
    ciudades, entrada = await con_cache(
        estado.cache_ciudades, clave, producir, saltar=pide_no_cache(request.headers), metricas=estado.metricas
    )
    response.headers["Cache-Status"] = entrada
    return ciudades


@router.get(
    "/ciudades/{id}/clima",
    summary="Clima actual y pronóstico por día de una ciudad",
    description=(
        "Encadena dos llamadas distintas a Open-Meteo: la ficha de la ciudad (geocoding `get`) y el "
        "pronóstico con sus coordenadas (D07). Las dos comparten un plazo de 15 s (D18). Caché de 24 h "
        "para la ficha y de 15 min para el pronóstico (D32); `Cache-Status` trae una entrada por cada una."
    ),
    responses={
        200: {"headers": CABECERA_CACHE},
        404: {"description": "Open-Meteo no conoce una ciudad con ese id (E6)"},
        **ERRORES_OPEN_METEO,
    },
)
async def clima_de_ciudad(
    request: Request,
    response: Response,
    id: Annotated[int, Path(ge=1, description="El id de la búsqueda, p. ej. 3688465 (Bucaramanga)")],
    dias: Annotated[int, Query(ge=1, le=16, description="Días de pronóstico, de 1 a 16 (E9)")] = 7,
) -> RespuestaClima:
    estado = request.app.state
    saltar = pide_no_cache(request.headers)
    fecha_limite = _fecha_limite(request)
    comunes = dict(politica=estado.politica_open_meteo, fecha_limite=fecha_limite, metricas=estado.metricas)

    async def producir_ciudad():
        ciudad = await open_meteo.obtener_ciudad(estado.cliente_geocoding, id, **comunes)
        if ciudad is None:
            # No se guarda en la caché: con_cache solo guarda lo que `producir` devuelve.
            raise HTTPException(404, f"No existe una ciudad con id {id}")
        return ciudad

    ciudad, entrada_ciudad = await con_cache(
        estado.cache_ciudades, ("ciudad", id), producir_ciudad, saltar=saltar, metricas=estado.metricas
    )

    async def producir_pronostico():
        return await open_meteo.pronosticar(estado.cliente_pronostico, ciudad, dias, **comunes)

    (zona, actual, por_dia), entrada_pronostico = await con_cache(
        estado.cache_pronostico, ("pronostico", id, dias), producir_pronostico, saltar=saltar, metricas=estado.metricas
    )
    response.headers["Cache-Status"] = f"{entrada_ciudad}, {entrada_pronostico}"
    return RespuestaClima(ciudad=ciudad, zona_horaria=zona, actual=actual, dias=por_dia)
