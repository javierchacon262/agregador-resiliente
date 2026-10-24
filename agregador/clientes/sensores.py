"""Cliente del servicio inestable: paginación y lecturas (funciones 7 y 8 de «D12 en detalle»).

Cada llamada pasa por `llamar_con_reintentos` con la compuerta compartida y la fecha
límite de la petición. Si algo falla del todo, se devuelve lo obtenido y el motivo
(D15); la ruta decide si eso alcanza para un 200 (D21).
"""

import asyncio
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from agregador.metricas import RegistroMetricas
from agregador.modelos import Lectura, LecturaServicio, PaginaSensores, SensorServicio
from agregador.resiliencia import CompuertaRetryAfter, ErrorDependencia, Politica, llamar_con_reintentos


@dataclass
class ResultadoPaginas:
    sensores: list[SensorServicio]
    completo: bool
    motivo: str | None = None
    causa: str | None = None  # la del fallo que cortó el recorrido, para elegir 502 o 504


@dataclass
class ResultadoLectura:
    lectura: Lectura | None
    motivo: str | None = None
    causa: str | None = None


# 7 ───────────────────────────────────────────────────────────────────────────────
async def recorrer_paginas(
    cliente: httpx.AsyncClient,
    *,
    politica: Politica,
    compuerta: CompuertaRetryAfter,
    fecha_limite: float,
    metricas: RegistroMetricas,
) -> ResultadoPaginas:
    """Pide /sensores y sigue el cursor `siguiente` hasta que sea null."""
    sensores: list[SensorServicio] = []
    cursor = None
    vistos: set[str] = set()
    pagina = 1
    while True:
        try:
            respuesta = await llamar_con_reintentos(
                cliente,
                "GET",
                "/sensores",
                params={"cursor": cursor} if cursor else None,
                politica=politica,
                compuerta=compuerta,
                fecha_limite=fecha_limite,
                metricas=metricas,
            )
        except ErrorDependencia as error:
            # Sin esta página no hay cursor para la siguiente: se corta aquí (M2).
            return ResultadoPaginas(sensores, False, f"la página {pagina} no respondió ({error.causa})", error.causa)
        if respuesta.status_code != 200:
            # Un 400 es un cursor que el servicio no reconoce: definitivo, no se reintenta.
            causa = str(respuesta.status_code)
            return ResultadoPaginas(sensores, False, f"la página {pagina} respondió {causa}", causa)
        try:
            datos = PaginaSensores.model_validate(respuesta.json())
        except ValueError:  # JSON roto o que no cumple el modelo
            return ResultadoPaginas(sensores, False, f"la página {pagina} no cumple el modelo", "respuesta_invalida")
        sensores.extend(datos.sensores)
        if datos.siguiente is None:
            return ResultadoPaginas(sensores, True)
        # Salvaguarda 6: si el servicio repite un cursor, se corta para no dar vueltas.
        if datos.siguiente in vistos:
            return ResultadoPaginas(sensores, False, "el servicio repitió un cursor", "respuesta_invalida")
        vistos.add(datos.siguiente)
        cursor = datos.siguiente
        pagina += 1


# 8 ───────────────────────────────────────────────────────────────────────────────
async def leer_lecturas(
    cliente: httpx.AsyncClient,
    ids: list[str],
    *,
    concurrencia: int,
    politica: Politica,
    compuerta: CompuertaRetryAfter,
    fecha_limite: float,
    metricas: RegistroMetricas,
) -> list[ResultadoLectura]:
    """Pide las lecturas con un máximo de `concurrencia` a la vez (D14), en el orden de `ids`."""
    semaforo = asyncio.Semaphore(concurrencia)

    async def leer(sensor_id: str) -> ResultadoLectura:
        async with semaforo:
            try:
                respuesta = await llamar_con_reintentos(
                    cliente,
                    "GET",
                    f"/sensores/{quote(sensor_id)}/lectura",
                    politica=politica,
                    compuerta=compuerta,
                    fecha_limite=fecha_limite,
                    metricas=metricas,
                )
            except ErrorDependencia as error:
                return ResultadoLectura(None, f"sin respuesta ({error.causa})", error.causa)
        if respuesta.status_code == 404:
            return ResultadoLectura(None, "el sensor no existe (404)", "404")
        if respuesta.status_code != 200:
            causa = str(respuesta.status_code)
            return ResultadoLectura(None, f"respondió {causa}", causa)
        try:
            datos = LecturaServicio.model_validate(respuesta.json())
        except ValueError:
            return ResultadoLectura(None, "la lectura no cumple el modelo", "respuesta_invalida")
        return ResultadoLectura(Lectura(valor=datos.valor, unidad=datos.unidad, marca_tiempo=datos.marca_tiempo))

    return await asyncio.gather(*(leer(sensor_id) for sensor_id in ids))
