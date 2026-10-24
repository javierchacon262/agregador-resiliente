"""Cliente de la API del grupo de Open Library: la Parte E del enunciado (D44).

Solo se usa lo que dice su contrato (`requirements/parte-e/openapi-grupo-open-library.json`):
`GET /v1/libros?titulo=` responde un `ResumenObra`, o 404 si no encontró una obra con
autor. La llamada pasa por `llamar_con_reintentos` con su propia política: 3 intentos,
timeouts de 4 → 6 → 8 s, plazo de 20 s y sin compuerta, porque no manda Retry-After
(D46).
"""

import httpx
from pydantic import BaseModel, ValidationError

from agregador import evidencia
from agregador.metricas import RegistroMetricas
from agregador.modelos import Libro
from agregador.resiliencia import ErrorDependencia, Politica, llamar_con_reintentos


class _ResumenObra(BaseModel):
    """El esquema `ResumenObra` de su contrato, tal como llega."""

    obra: str
    autor: str
    clave_autor: str
    nombre_personal_real: str | None = None
    fecha_nacimiento: str | None = None


def _error(causa: str, detalle: str) -> ErrorDependencia:
    return ErrorDependencia("otro_grupo", causa, evidencia.peticion_actual().intentos, detalle)


async def buscar_libro(
    cliente: httpx.AsyncClient,
    titulo: str,
    *,
    politica: Politica,
    fecha_limite: float,
    metricas: RegistroMetricas | None = None,
) -> Libro | None:
    """La obra y su autor para un título, o None si su API responde 404."""
    respuesta = await llamar_con_reintentos(
        cliente,
        "GET",
        "/v1/libros",
        params={"titulo": titulo},
        politica=politica,
        fecha_limite=fecha_limite,
        metricas=metricas,
    )
    # Su contrato documenta el 404 como «No se encontró una obra con autor». Llega aquí
    # sin reintentar, porque un 404 es definitivo (D12).
    if respuesta.status_code == 404:
        return None
    if respuesta.is_error:
        # Otro 4xx no debería pasar (validamos el título con su misma regla). Su 502 y
        # su 504 los atrapa antes llamar_con_reintentos. En los dos casos, 502 (D20).
        raise _error(str(respuesta.status_code), f"La API del grupo de Open Library respondió {respuesta.status_code}")
    try:
        externo = _ResumenObra.model_validate_json(respuesta.content)
    except ValidationError as error:
        # Por ejemplo, la página HTML que manda Cloudflare cuando su túnel falla.
        raise _error(
            "respuesta_invalida",
            f"La API del grupo de Open Library respondió algo que no cumple su contrato ({error.error_count()} errores)",
        ) from None
    return Libro(**externo.model_dump())
