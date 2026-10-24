"""Log de evidencias de los reintentos (D37).

Una línea por intento y una final por petición, por stdout y en UTC, con la misma forma
de hora que el log del servicio inestable para poder leer los dos lado a lado:

    [16:40:04.512] r-7f3a sensores 2/6 GET /sensores -> 429 · Retry-After 2 s · espera 2,00 s
    [16:40:06.540] r-7f3a GET /v1/sensores -> 200 completo (2,30 s, 3 intentos)
"""

import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone

# /salud no deja líneas: el healthcheck la llama cada pocos segundos y taparía la
# evidencia (C7).
RUTAS_SIN_LOG = frozenset({"/salud"})


@dataclass
class EstadoPeticion:
    """Lo que se va sabiendo de la petición en curso, para su línea final."""

    id: str = field(default_factory=lambda: f"r-{secrets.token_hex(2)}")
    intentos: int = 0
    nota: str = ""  # la pone la ruta, p. ej. «completo» o «incompleto»


_peticion: ContextVar[EstadoPeticion | None] = ContextVar("peticion", default=None)


def iniciar_peticion() -> EstadoPeticion:
    estado = EstadoPeticion()
    _peticion.set(estado)
    return estado


def peticion_actual() -> EstadoPeticion:
    estado = _peticion.get()
    if estado is None:  # fuera de una petición, como en las pruebas unitarias
        estado = iniciar_peticion()
    return estado


def segundos(valor: float) -> str:
    """2.0 → «2,00 s»: decimales con coma, como el resto de los documentos."""
    return f"{valor:.2f} s".replace(".", ",")


def escribir(texto: str) -> None:
    hora = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    print(f"[{hora}] {peticion_actual().id} {texto}", flush=True)


class MiddlewareEvidencia:
    """Abre el contexto de cada petición y escribe su línea final.

    Es ASGI puro, no BaseHTTPMiddleware, para que la ruta corra en la misma tarea y el
    estado de la petición le llegue sin copias. También anota la latencia por ruta en
    las métricas (D35).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in RUTAS_SIN_LOG:
            await self.app(scope, receive, send)
            return

        estado = iniciar_peticion()
        inicio = time.perf_counter()
        codigo = 500

        async def enviar(mensaje):
            nonlocal codigo
            if mensaje["type"] == "http.response.start":
                codigo = mensaje["status"]
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        finally:
            duracion = time.perf_counter() - inicio
            # La plantilla de la ruta (/v1/alertas/{id}) agrupa mejor que la URL.
            ruta = getattr(scope.get("route"), "path", scope["path"])
            metricas = getattr(scope["app"].state, "metricas", None)
            if metricas is not None:
                metricas.registrar_latencia(ruta, duracion)
            nota = f" {estado.nota}" if estado.nota else ""
            intentos = ""
            if estado.intentos:
                intentos = f", {estado.intentos} intento{'s' if estado.intentos > 1 else ''}"
            escribir(f"{scope['method']} {scope['path']} -> {codigo}{nota} ({segundos(duracion)}{intentos})")
