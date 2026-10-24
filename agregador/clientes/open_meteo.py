"""Cliente de Open-Meteo: buscar ciudades, traer una por id y pedir su pronóstico.

Son dos servicios distintos (geocoding y forecast) y tres llamadas; el clima encadena
`obtener_ciudad` → `pronosticar` (D07, E5). Toda llamada pasa por
`llamar_con_reintentos` con la política de Open-Meteo: 3 intentos y sin compuerta,
porque Open-Meteo no manda Retry-After (D22, E10).

Lo que llega se valida con los modelos externos de abajo antes de convertirlo a los
modelos propios: una respuesta que no cumple el modelo es un 502, nunca datos a medias
(HU2, Parte A.5 del enunciado).
"""

from datetime import date, datetime

import httpx
from pydantic import BaseModel, ValidationError, model_validator

from agregador import evidencia
from agregador.metricas import RegistroMetricas
from agregador.modelos import Ciudad, ClimaActual, DiaPronostico
from agregador.resiliencia import ErrorDependencia, Politica, llamar_con_reintentos

# Detalle 8 del canvas: lo que se le pide al pronóstico.
VARIABLES_ACTUAL = "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
VARIABLES_DIARIAS = "temperature_2m_max,temperature_2m_min,precipitation_probability_max"
CANDIDATOS = 10  # los que devuelve Open-Meteo por defecto; «San José» llena los 10 (E3)


# Modelos externos: los nombres de Open-Meteo, tal como llegan ──────────────────────


class _CiudadExterna(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    admin1: str | None = None
    country: str | None = None
    country_code: str | None = None
    population: int | None = None

    def a_ciudad(self) -> Ciudad:
        return Ciudad(
            id=self.id,
            nombre=self.name,
            departamento=self.admin1,
            pais=self.country,
            codigo_pais=self.country_code,
            latitud=self.latitude,
            longitud=self.longitude,
            poblacion=self.population,
        )


class _BusquedaExterna(BaseModel):
    # Sin coincidencias, Open-Meteo responde 200 y omite `results` (E1).
    results: list[_CiudadExterna] = []


class _ActualExterno(BaseModel):
    time: datetime
    temperature_2m: float
    relative_humidity_2m: float
    weather_code: int
    wind_speed_10m: float


class _DiarioExterno(BaseModel):
    """Listas paralelas, una por variable (E7). Se juntan por día solo si tienen el
    mismo largo; si no, no hay forma segura de saber qué valor es de qué día."""

    time: list[date]
    temperature_2m_max: list[float | None]
    temperature_2m_min: list[float | None]
    precipitation_probability_max: list[float | None]

    @model_validator(mode="after")
    def mismo_largo(self):
        largos = {
            len(self.time),
            len(self.temperature_2m_max),
            len(self.temperature_2m_min),
            len(self.precipitation_probability_max),
        }
        if len(largos) != 1:
            raise ValueError(f"las listas diarias no tienen el mismo largo: {sorted(largos)}")
        return self


class _PronosticoExterno(BaseModel):
    timezone: str
    current: _ActualExterno
    daily: _DiarioExterno


# Llamadas ────────────────────────────────────────────────────────────────────────


def _invalida(detalle: str) -> ErrorDependencia:
    # D20: datos que no cumplen el modelo → 502, con la causa «respuesta_invalida».
    return ErrorDependencia(
        "open_meteo", "respuesta_invalida", evidencia.peticion_actual().intentos, f"Open-Meteo {detalle}"
    )


def _rechazada(respuesta: httpx.Response) -> ErrorDependencia:
    # Un 4xx que no esperábamos: no se reintenta (D12) y no es culpa del cliente de
    # nuestra API, así que es un fallo de la dependencia → 502 (D20).
    return ErrorDependencia(
        "open_meteo",
        str(respuesta.status_code),
        evidencia.peticion_actual().intentos,
        f"Open-Meteo rechazó la consulta con {respuesta.status_code}: {_razon(respuesta)}",
    )


def _razon(respuesta: httpx.Response) -> str:
    """El campo `reason` de los errores de Open-Meteo (E6, E8), si viene."""
    try:
        return str(respuesta.json().get("reason", ""))
    except (ValueError, AttributeError):
        return ""


def _validar(modelo: type[BaseModel], respuesta: httpx.Response, que: str):
    try:
        return modelo.model_validate_json(respuesta.content)
    except ValidationError as error:
        raise _invalida(f"respondió {que} que no cumple el modelo ({error.error_count()} errores)") from None


async def buscar(
    cliente: httpx.AsyncClient,
    nombre: str,
    pais: str | None,
    *,
    politica: Politica,
    fecha_limite: float,
    metricas: RegistroMetricas | None = None,
) -> list[Ciudad]:
    """Candidatos para un nombre, con su departamento y país (D05). Lista vacía si no
    hay ninguno (D36)."""
    params = {"name": nombre, "count": CANDIDATOS, "language": "es"}
    if pais:
        params["countryCode"] = pais  # E4
    respuesta = await llamar_con_reintentos(
        cliente, "GET", "/v1/search", params=params, politica=politica, fecha_limite=fecha_limite, metricas=metricas
    )
    if respuesta.is_error:
        raise _rechazada(respuesta)
    return [resultado.a_ciudad() for resultado in _validar(_BusquedaExterna, respuesta, "una búsqueda").results]


async def obtener_ciudad(
    cliente: httpx.AsyncClient,
    id_ciudad: int,
    *,
    politica: Politica,
    fecha_limite: float,
    metricas: RegistroMetricas | None = None,
) -> Ciudad | None:
    """La ficha de una ciudad por su id, o None si Open-Meteo no la conoce."""
    respuesta = await llamar_con_reintentos(
        cliente,
        "GET",
        "/v1/get",
        params={"id": id_ciudad, "language": "es"},
        politica=politica,
        fecha_limite=fecha_limite,
        metricas=metricas,
    )
    # Un id inexistente da 400 «Location ID not found.» (E6). Llega aquí sin reintentar,
    # porque un 400 es definitivo. Pero no todo 400 es «no existe»: se mira el motivo.
    if respuesta.status_code == 400 and "not found" in _razon(respuesta).lower():
        return None
    if respuesta.is_error:
        raise _rechazada(respuesta)
    return _validar(_CiudadExterna, respuesta, "una ficha de ciudad").a_ciudad()


async def pronosticar(
    cliente: httpx.AsyncClient,
    ciudad: Ciudad,
    dias: int,
    *,
    politica: Politica,
    fecha_limite: float,
    metricas: RegistroMetricas | None = None,
) -> tuple[str, ClimaActual, list[DiaPronostico]]:
    """Zona horaria, clima actual y la lista por día para las coordenadas de la ciudad."""
    params = {
        "latitude": ciudad.latitud,
        "longitude": ciudad.longitud,
        "current": VARIABLES_ACTUAL,
        "daily": VARIABLES_DIARIAS,
        "timezone": "auto",
        "forecast_days": dias,
    }
    respuesta = await llamar_con_reintentos(
        cliente, "GET", "/v1/forecast", params=params, politica=politica, fecha_limite=fecha_limite, metricas=metricas
    )
    if respuesta.is_error:
        raise _rechazada(respuesta)
    externo = _validar(_PronosticoExterno, respuesta, "un pronóstico")

    actual = ClimaActual(
        hora=externo.current.time,
        temperatura_c=externo.current.temperature_2m,
        humedad_pct=externo.current.relative_humidity_2m,
        codigo_tiempo=externo.current.weather_code,
        viento_kmh=externo.current.wind_speed_10m,
    )
    diario = externo.daily
    # De listas paralelas a una lista por día (E7); el largo ya se validó.
    por_dia = [
        DiaPronostico(fecha=fecha, maxima_c=maxima, minima_c=minima, prob_lluvia_pct=lluvia)
        for fecha, maxima, minima, lluvia in zip(
            diario.time, diario.temperature_2m_max, diario.temperature_2m_min, diario.precipitation_probability_max
        )
    ]
    return externo.timezone, actual, por_dia
