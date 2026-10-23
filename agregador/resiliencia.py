"""Reintentos a mano (D12), función por función como en «D12 en detalle» del README.

Toda llamada saliente pasa por `llamar_con_reintentos`. Las reglas salen de D12 y
D17–D22; los números (intentos, timeouts, backoff) llegan en una `Politica` armada
desde la configuración, y el plazo, en la fecha límite de cada petición.
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import httpx

from agregador import evidencia
from agregador.metricas import RegistroMetricas

Reloj = Callable[[], float]
Dormir = Callable[[float], Awaitable[None]]
Azar = Callable[[float, float], float]

# Errores de red pasajeros: conexión rechazada, cortada o con el protocolo roto a mitad
# de camino (D22). Un error de configuración, como una URL sin esquema, no entra.
ERRORES_DE_CONEXION = (httpx.NetworkError, httpx.RemoteProtocolError)

NOMBRES = {"servicio_inestable": "El servicio inestable", "open_meteo": "Open-Meteo"}


@dataclass(frozen=True)
class Politica:
    """Los números de los reintentos hacia una dependencia."""

    dependencia: str  # en métricas y errores: «servicio_inestable» u «open_meteo»
    etiqueta: str  # en el log de evidencias: «sensores» u «open-meteo»
    maximo: int  # D17 (6) y D22 (3)
    timeouts_lectura: tuple[float, ...]  # D19
    timeout_conexion: float
    base: float  # D12
    tope: float


class ErrorDependencia(Exception):
    """La dependencia no dio una respuesta usable; la ruta responde 502 o 504 (D20)."""

    def __init__(self, dependencia: str, causa: str, intentos: int, detalle: str):
        super().__init__(detalle)
        self.dependencia = dependencia
        self.causa = causa
        self.intentos = intentos
        self.detalle = detalle

    @property
    def codigo(self) -> int:
        # D20: 504 si no respondió a tiempo (el último intento o el plazo de la
        # petición); 502 si respondió con un error o con algo inválido.
        return 504 if self.causa in ("timeout", "plazo") else 502


# 1 ───────────────────────────────────────────────────────────────────────────────
def es_reintentable(resultado: httpx.Response | Exception) -> bool:
    """¿Vale la pena repetir? Sí con 503, 429, timeout y errores de conexión.

    Un 503, un 429 o una red caída son pasajeros; un 400 o un 404 son definitivos, y
    repetirlos solo gasta peticiones de la dependencia (D12, D22).
    """
    if isinstance(resultado, Exception):
        return isinstance(resultado, (httpx.TimeoutException, *ERRORES_DE_CONEXION))
    return resultado.status_code in (429, 503)


# 2 ───────────────────────────────────────────────────────────────────────────────
def leer_retry_after(respuesta: httpx.Response) -> float | None:
    """Segundos que pide esperar la cabecera Retry-After, o None si no viene o no sirve.

    El servicio manda segundos enteros; RFC 9110 también permite una fecha HTTP.
    """
    valor = respuesta.headers.get("Retry-After")
    if valor is None:
        return None
    valor = valor.strip()
    if valor.isdigit():
        return float(valor)
    try:
        fecha = parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return max(0.0, (fecha - datetime.now(timezone.utc)).total_seconds())


# 3 ───────────────────────────────────────────────────────────────────────────────
def calcular_espera(
    intento: int, retry_after: float | None, base: float, tope: float, azar: Azar = random.uniform
) -> float:
    """Backoff exponencial con jitter completo: azar(0, mín(tope, base · 2^intento)).

    El azar evita que muchos clientes que fallan a la vez vuelvan todos juntos. Si vino
    Retry-After, se espera al menos eso: nunca hay que volver antes de lo que pidió el
    servidor.
    """
    espera = azar(0, min(tope, base * 2**intento))
    if retry_after is not None:
        espera = max(retry_after, espera)
    return espera


# 4 ───────────────────────────────────────────────────────────────────────────────
def timeout_para(intento: int, timeouts_lectura: tuple[float, ...]) -> float:
    """Timeout de lectura del intento (D19): 3 s, 6 s y 8 s del tercero en adelante.

    El primero corta rápido una respuesta lenta, porque el siguiente intento suele caer
    en una normal; los demás dan margen. 6 s y no 5 s: con --latencia 5 el servicio
    duerme 5 s antes de responder (M4).
    """
    return timeouts_lectura[min(intento, len(timeouts_lectura) - 1)]


# 5 ───────────────────────────────────────────────────────────────────────────────
class CompuertaRetryAfter:
    """Una sola, compartida por todas las llamadas al servicio inestable (D14).

    El servicio bloquea por IP: un 429 vale para todas nuestras llamadas, no solo para
    la que lo recibió. Sin compuerta, las llamadas en vuelo saldrían antes de tiempo y
    el log del docente las mostraría como «no respetó Retry-After».
    """

    def __init__(self, reloj: Reloj = time.monotonic, dormir: Dormir = asyncio.sleep, ventana_envio: float = 0.25):
        self._hasta = 0.0
        self._reloj = reloj
        self._dormir = dormir
        # Turno de envío (C8): las peticiones salen de a una, y cada una retiene el turno
        # hasta que llega su respuesta o pasa `ventana_envio`. El servicio decide el 429
        # antes de dormir, así que vuelve en milisegundos y cierra la compuerta antes de
        # que salga la siguiente. Una respuesta lenta suelta el turno al vencer la
        # ventana, y las lecturas siguen en paralelo (D14).
        self.ventana_envio = ventana_envio
        self.turno = asyncio.Lock()

    @property
    def hasta(self) -> float:
        return self._hasta

    def falta(self) -> float:
        return max(0.0, self._hasta - self._reloj())

    def cerrar_hasta(self, instante: float) -> None:
        """Guarda hasta cuándo no se puede llamar; si ya había un cierre más largo, gana ese."""
        self._hasta = max(self._hasta, instante)

    async def esperar(self) -> None:
        # En bucle: mientras se duerme, otro 429 puede alargar el cierre.
        while (falta := self.falta()) > 0:
            await self._dormir(falta)


# 6 ───────────────────────────────────────────────────────────────────────────────
async def llamar_con_reintentos(
    cliente: httpx.AsyncClient,
    metodo: str,
    url: str,
    *,
    politica: Politica,
    fecha_limite: float,
    compuerta: CompuertaRetryAfter | None = None,
    metricas: RegistroMetricas | None = None,
    params: dict | None = None,
    reloj: Reloj = time.monotonic,
    dormir: Dormir = asyncio.sleep,
    azar: Azar = random.uniform,
) -> httpx.Response:
    """El ciclo que une todo. Devuelve la respuesta (2xx, o un 4xx definitivo como el
    404, que la ruta traduce) o lanza `ErrorDependencia` si se rinde.

    `fecha_limite` es un instante de `reloj`: la fija la ruta al recibir la petición y
    la comparten todas sus llamadas, así que ninguna respuesta pasa de su plazo (D18).
    """
    destino = f"{url}?{urlencode(params)}" if params else url
    nombre = NOMBRES.get(politica.dependencia, politica.dependencia)
    if metricas:
        metricas.registrar_llamada(politica.dependencia)

    def registrar(intento: int, resultado: str) -> None:
        evidencia.escribir(f"{politica.etiqueta} {intento + 1}/{politica.maximo} {metodo} {destino} -> {resultado}")

    def rendirse(causa: str, intentos: int) -> ErrorDependencia:
        detalles = {
            "plazo": f"{nombre} no respondió dentro del plazo de la petición",
            "timeout": f"{nombre} no respondió a tiempo en {intentos} intentos",
            "conexion": f"No se pudo conectar con {nombre} en {intentos} intentos",
        }
        detalle = detalles.get(causa, f"{nombre} respondió {causa} en {intentos} intentos")
        return ErrorDependencia(politica.dependencia, causa, intentos, detalle)

    causa = "plazo"
    async def enviar(restante: float, timeout: httpx.Timeout) -> httpx.Response:
        # El timeout de httpx corta cada intento (D19); el de asyncio garantiza que el
        # intento tampoco pase del plazo de la petición (D18).
        async with asyncio.timeout(restante):
            respuesta = await cliente.request(metodo, url, params=params, timeout=timeout)
        # Un 429 cierra la compuerta aquí mismo, antes de que se suelte el turno de
        # envío: así ninguna otra llamada sale sin saberlo (C8).
        if compuerta is not None and respuesta.status_code == 429:
            if (retry_after := leer_retry_after(respuesta)) is not None:
                compuerta.cerrar_hasta(reloj() + retry_after)
        return respuesta

    enviados = 0
    for intento in range(politica.maximo):
        async with compuerta.turno if compuerta is not None else nullcontext():
            if compuerta is not None and compuerta.falta() > 0:
                if compuerta.hasta >= fecha_limite:
                    registrar(intento, "no sale: la compuerta abre después del plazo")
                    raise rendirse("plazo", enviados)
                registrar(intento, f"espera la compuerta {evidencia.segundos(compuerta.falta())}")
                await compuerta.esperar()

            restante = fecha_limite - reloj()
            if restante <= 0:
                raise rendirse("plazo", enviados)
            lectura = min(timeout_para(intento, politica.timeouts_lectura), restante)
            timeout = httpx.Timeout(lectura, connect=min(politica.timeout_conexion, restante))

            enviados += 1
            evidencia.peticion_actual().intentos += 1
            inicio = reloj()
            tarea = asyncio.ensure_future(enviar(restante, timeout))
            if compuerta is not None:
                try:
                    await asyncio.wait({tarea}, timeout=compuerta.ventana_envio)
                except asyncio.CancelledError:
                    tarea.cancel()
                    raise

        respuesta = None
        retry_after = None
        try:
            respuesta = await tarea
        except TimeoutError:
            causa, resultado = "plazo", "plazo agotado"
        except httpx.TimeoutException:
            causa, resultado = "timeout", f"timeout ({evidencia.segundos(reloj() - inicio)})"
        except ERRORES_DE_CONEXION as error:
            causa, resultado = "conexion", f"conexión fallida ({type(error).__name__})"

        if respuesta is not None:
            codigo = respuesta.status_code
            resultado = f"{codigo} ({round((reloj() - inicio) * 1000)} ms)"
            if not es_reintentable(respuesta):
                if metricas:
                    metricas.registrar_intento(politica.dependencia, str(codigo))
                if codigo >= 500:
                    # Otro 5xx (500, 502, 504…): no es pasajero según D12, así que no se
                    # repite, y la ruta responde 502 (D20).
                    registrar(intento, f"{resultado} · no se reintenta")
                    raise rendirse(str(codigo), enviados)
                registrar(intento, resultado)
                return respuesta
            causa = str(codigo)
            retry_after = leer_retry_after(respuesta)
            if retry_after is not None:
                resultado += f" · Retry-After {retry_after:g} s"

        if metricas:
            metricas.registrar_intento(politica.dependencia, causa)
        if causa == "plazo":
            registrar(intento, resultado)
            break
        if intento + 1 >= politica.maximo:
            registrar(intento, f"{resultado} · intentos agotados")
            break
        espera = calcular_espera(intento, retry_after, politica.base, politica.tope, azar)
        if reloj() + espera >= fecha_limite:
            registrar(intento, f"{resultado} · no hay tiempo para esperar {evidencia.segundos(espera)}")
            causa = "plazo"
            break
        registrar(intento, f"{resultado} · espera {evidencia.segundos(espera)}")
        await dormir(espera)

    raise rendirse(causa, enviados)
