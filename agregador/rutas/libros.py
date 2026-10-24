"""GET /v1/libros: la Parte E, consumo cruzado (D44, D45).

Le pregunta a la API del grupo de Open Library por un título, usando solo su contrato
OpenAPI, y responde lo mismo que ella con sus mismos nombres de campo. Se cachea 24 h
(D47). Si su servidor no está, solo falla esta ruta.
"""

import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from agregador.cache import con_cache, pide_no_cache
from agregador.clientes import otro_grupo
from agregador.modelos import CuerpoErrorDependencia, Libro

router = APIRouter(prefix="/v1", tags=["libros (Parte E)"])


@router.get(
    "/libros",
    summary="Buscar una obra y su autor en la API de otro grupo",
    description=(
        "Consumo cruzado (Parte E): pregunta a la API del grupo de Open Library, `GET /v1/libros?titulo=`, "
        "y devuelve su respuesta con los mismos campos. Hasta 3 intentos y 20 s por petición (D46); "
        "caché de 24 h (D47), que `Cache-Control: no-cache` se salta."
    ),
    responses={
        200: {
            "headers": {
                "Cache-Status": {
                    "description": "RFC 9211: si salió de la caché (hit) o de su API (fwd) (D33)",
                    "schema": {"type": "string"},
                }
            }
        },
        404: {"description": "Su API no encontró una obra con autor para ese título"},
        502: {"model": CuerpoErrorDependencia, "description": "Su API falló o respondió algo que no cumple su contrato"},
        504: {"model": CuerpoErrorDependencia, "description": "Su API no respondió a tiempo o se agotó el plazo de 20 s"},
    },
)
async def buscar_libro(
    request: Request,
    response: Response,
    titulo: Annotated[
        str,
        Query(
            min_length=1,  # su misma regla (minLength: 1)
            max_length=200,
            description="Título de la obra, p. ej. «Cien años de soledad»",
        ),
    ],
) -> Libro:
    estado = request.app.state
    # La fecha límite la comparten todos los intentos de esta petición (D18, D46).
    fecha_limite = time.monotonic() + estado.config.plazo_otro_grupo_s
    titulo = titulo.strip()
    if not titulo:
        # Solo espacios: sin ellos queda vacío, y su API lo rechazaría (minLength: 1).
        raise HTTPException(422, "El título no puede estar vacío")

    async def producir():
        libro = await otro_grupo.buscar_libro(
            estado.cliente_otro_grupo,
            titulo,
            politica=estado.politica_otro_grupo,
            fecha_limite=fecha_limite,
            metricas=estado.metricas,
        )
        if libro is None:
            # No se guarda en la caché: con_cache solo guarda lo que `producir` devuelve.
            raise HTTPException(404, f"La API del grupo de Open Library no encontró una obra con autor para «{titulo}»")
        return libro

    libro, entrada = await con_cache(
        estado.cache_libros,
        ("libro", titulo.casefold()),
        producir,
        saltar=pide_no_cache(request.headers),
        metricas=estado.metricas,
    )
    response.headers["Cache-Status"] = entrada
    return libro
