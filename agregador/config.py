"""Configuración del agregador, leída de variables de entorno.

Cada variable sale de la tabla de Norms del canvas, con la decisión que la fija. Todas
tienen valor por defecto, así que el agregador arranca sin configurar nada (D28).
"""

import os
from dataclasses import dataclass


def _texto(nombre: str, defecto: str) -> str:
    return os.environ.get(nombre, defecto)


def _numero(nombre: str, defecto: float) -> float:
    return float(os.environ.get(nombre, defecto))


def _entero(nombre: str, defecto: int) -> int:
    return int(os.environ.get(nombre, defecto))


def _numeros(nombre: str, defecto: str) -> tuple[float, ...]:
    return tuple(float(parte) for parte in os.environ.get(nombre, defecto).split(","))


@dataclass(frozen=True)
class Configuracion:
    servicio_inestable_url: str
    open_meteo_geocoding_url: str
    open_meteo_forecast_url: str
    maximo_intentos_sensores: int
    maximo_intentos_open_meteo: int
    plazo_sensores_s: float
    plazo_open_meteo_s: float
    timeouts_lectura_s: tuple[float, ...]
    timeout_conexion_s: float
    backoff_base_s: float
    backoff_tope_s: float
    concurrencia_lecturas: int
    ventana_envio_s: float
    ttl_ciudades_s: float
    ttl_pronostico_s: float
    ttl_idempotencia_s: float
    otro_grupo_url: str
    maximo_intentos_otro_grupo: int
    plazo_otro_grupo_s: float
    timeouts_lectura_otro_grupo_s: tuple[float, ...]
    ttl_libros_s: float


def cargar_configuracion() -> Configuracion:
    return Configuracion(
        servicio_inestable_url=_texto("SERVICIO_INESTABLE_URL", "http://servicio-inestable:9000"),  # D30
        open_meteo_geocoding_url=_texto("OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com"),
        open_meteo_forecast_url=_texto("OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com"),
        maximo_intentos_sensores=_entero("MAXIMO_INTENTOS_SENSORES", 6),  # D17
        maximo_intentos_open_meteo=_entero("MAXIMO_INTENTOS_OPEN_METEO", 3),  # D22
        plazo_sensores_s=_numero("PLAZO_SENSORES_S", 45),  # D18
        plazo_open_meteo_s=_numero("PLAZO_OPEN_METEO_S", 15),  # D18
        timeouts_lectura_s=_numeros("TIMEOUTS_LECTURA_S", "3,6,8"),  # D19
        timeout_conexion_s=_numero("TIMEOUT_CONEXION_S", 2),
        backoff_base_s=_numero("BACKOFF_BASE_S", 0.5),  # D12
        backoff_tope_s=_numero("BACKOFF_TOPE_S", 8),  # D12
        concurrencia_lecturas=_entero("CONCURRENCIA_LECTURAS", 4),  # D14
        ventana_envio_s=_numero("VENTANA_ENVIO_S", 0.25),  # C8: turno de envío al servicio inestable
        ttl_ciudades_s=_numero("TTL_CIUDADES_S", 86400),  # D32
        ttl_pronostico_s=_numero("TTL_PRONOSTICO_S", 900),  # D32
        ttl_idempotencia_s=_numero("TTL_IDEMPOTENCIA_S", 86400),  # D25
        # Parte E: la API del grupo de Open Library (D44). Su URL es la de un túnel
        # rápido de Cloudflare, que cambia si lo reinician (D48).
        otro_grupo_url=_texto("OTRO_GRUPO_URL", "https://validation-seed-grill-junior.trycloudflare.com"),
        maximo_intentos_otro_grupo=_entero("MAXIMO_INTENTOS_OTRO_GRUPO", 3),  # D46
        plazo_otro_grupo_s=_numero("PLAZO_OTRO_GRUPO_S", 20),  # D46
        timeouts_lectura_otro_grupo_s=_numeros("TIMEOUTS_LECTURA_OTRO_GRUPO_S", "4,6,8"),  # D46
        ttl_libros_s=_numero("TTL_LIBROS_S", 86400),  # D47
    )
