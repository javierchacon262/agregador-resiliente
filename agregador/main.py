"""Aplicación FastAPI del agregador: arranque, evidencia, errores de dependencias y rutas."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agregador.cache import CacheTTL
from agregador.config import cargar_configuracion
from agregador.evidencia import MiddlewareEvidencia
from agregador.idempotencia import AlmacenIdempotencia
from agregador.metricas import RegistroMetricas
from agregador.modelos import CuerpoErrorDependencia, Salud
from agregador.resiliencia import CompuertaRetryAfter, ErrorDependencia, Politica
from agregador.rutas import alertas, ciudades, libros, metricas, sensores


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = cargar_configuracion()
    estado = app.state
    estado.config = config
    estado.metricas = RegistroMetricas()
    # Una sola compuerta para todas las llamadas al servicio inestable (D14).
    estado.compuerta = CompuertaRetryAfter(ventana_envio=config.ventana_envio_s)
    # Cachés en memoria con su TTL (D32); los nombres van en Cache-Status (D33).
    estado.cache_ciudades = CacheTTL("agregador-ciudades", config.ttl_ciudades_s)
    estado.cache_pronostico = CacheTTL("agregador-pronostico", config.ttl_pronostico_s)
    estado.cache_libros = CacheTTL("agregador-libros", config.ttl_libros_s)  # D47
    # Alertas y claves de idempotencia, también en memoria (D24, D25).
    estado.alertas = alertas.RegistroAlertas()
    estado.idempotencia = AlmacenIdempotencia(config.ttl_idempotencia_s)
    comunes = dict(
        timeouts_lectura=config.timeouts_lectura_s,
        timeout_conexion=config.timeout_conexion_s,
        base=config.backoff_base_s,
        tope=config.backoff_tope_s,
    )
    estado.politica_sensores = Politica(
        dependencia="servicio_inestable", etiqueta="sensores", maximo=config.maximo_intentos_sensores, **comunes
    )
    estado.politica_open_meteo = Politica(
        dependencia="open_meteo", etiqueta="open-meteo", maximo=config.maximo_intentos_open_meteo, **comunes
    )
    # Parte E: sus propios timeouts, 10 s por intento, porque su API tarda segundos (D50).
    estado.politica_otro_grupo = Politica(
        dependencia="otro_grupo",
        etiqueta="otro-grupo",
        maximo=config.maximo_intentos_otro_grupo,
        **(comunes | {"timeouts_lectura": config.timeouts_lectura_otro_grupo_s}),
    )
    # Un cliente por dependencia, que reutiliza conexiones. Cada llamada lleva su propio
    # timeout; este es solo el de respaldo.
    respaldo = httpx.Timeout(max(config.timeouts_lectura_s), connect=config.timeout_conexion_s)
    async with (
        httpx.AsyncClient(base_url=config.servicio_inestable_url, timeout=respaldo) as sensores,
        httpx.AsyncClient(base_url=config.open_meteo_geocoding_url, timeout=respaldo) as geocoding,
        httpx.AsyncClient(base_url=config.open_meteo_forecast_url, timeout=respaldo) as pronostico,
        httpx.AsyncClient(base_url=config.otro_grupo_url, timeout=respaldo) as otro,
    ):
        estado.cliente_otro_grupo = otro
        estado.cliente_sensores = sensores
        estado.cliente_geocoding = geocoding
        estado.cliente_pronostico = pronostico
        yield


app = FastAPI(
    title="Agregador resiliente",
    description=(
        "Combina el clima de Open-Meteo con los sensores de un servicio que falla a propósito, "
        "y sigue respondiendo aunque sus dependencias fallen: reintentos selectivos con backoff "
        "y jitter, respeto de Retry-After, caché e idempotencia."
    ),
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(MiddlewareEvidencia)
app.include_router(ciudades.router)
app.include_router(sensores.router)
app.include_router(alertas.router)
app.include_router(libros.router)
app.include_router(metricas.router)


@app.exception_handler(ErrorDependencia)
async def responder_error_dependencia(request: Request, error: ErrorDependencia) -> JSONResponse:
    """Un fallo de una dependencia nunca sale como 500: 502 o 504 según D20."""
    request.app.state.metricas.registrar_error_dependencia(error.dependencia, error.codigo)
    cuerpo = CuerpoErrorDependencia(
        detalle=error.detalle, dependencia=error.dependencia, causa=error.causa, intentos=error.intentos
    )
    return JSONResponse(status_code=error.codigo, content=cuerpo.model_dump())


@app.get("/salud", tags=["salud"], summary="Comprobación de vida; no consulta las dependencias")
async def salud() -> Salud:
    return Salud(estado="ok")
