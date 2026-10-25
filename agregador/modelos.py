"""Modelos Pydantic de la API propia (Entities del canvas).

Son el contrato que muestra /docs (Parte B del enunciado). Los de cada ruta se agregan
con su tarea; aquí están los de la base común.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Salud(BaseModel):
    estado: Literal["ok"]


class CuerpoErrorDependencia(BaseModel):
    """Cuerpo de los 502 y 504 cuando falla una dependencia (D20)."""

    detalle: str = Field(examples=["El servicio inestable no respondió dentro del plazo de la petición"])
    dependencia: Literal["servicio_inestable", "open_meteo", "otro_grupo"]
    causa: str = Field(
        description="timeout, plazo, conexion, respuesta_invalida, o el código que respondió (503, 429, 500…)",
        examples=["plazo"],
    )
    intentos: int = Field(description="Intentos enviados antes de rendirse", examples=[6])


class MetricasDependencia(BaseModel):
    llamadas: int = Field(description="Llamadas lógicas: cada una puede llevar varios intentos")
    intentos: int
    reintentos: int = Field(description="Intentos de más sobre la primera de cada llamada")
    por_resultado: dict[str, int] = Field(
        description="Intentos por resultado: el código («200», «503», «429»…) o la causa (timeout, conexion, plazo)",
        examples=[{"200": 230, "429": 38, "503": 121, "timeout": 21}],
    )
    respuestas_502: int
    respuestas_504: int
    compuerta_cerrada_hasta: datetime | None = Field(
        default=None, description="Solo el servicio inestable: hasta cuándo frena la compuerta de Retry-After (D14)"
    )


class MetricasCache(BaseModel):
    aciertos: int
    fallos: int


class LatenciaRuta(BaseModel):
    peticiones: int = Field(description="Peticiones en la ventana (las últimas 100)")
    mediana: float = Field(description="Milisegundos")
    p95: float = Field(description="Milisegundos")


class Metricas(BaseModel):
    """Lo que lee el panel de resiliencia del dashboard (D35). Cuenta desde el arranque."""

    desde: datetime
    dependencias: dict[Literal["servicio_inestable", "open_meteo", "otro_grupo"], MetricasDependencia]
    cache: MetricasCache
    latencia_ms: dict[str, LatenciaRuta] = Field(description="Por plantilla de ruta, p. ej. /v1/alertas/{id}")


# Ciudades y clima (HU1, HU2) ─────────────────────────────────────────────────────


class Ciudad(BaseModel):
    """Un candidato de la búsqueda, o la ciudad resuelta por id (D05, D07)."""

    id: int = Field(examples=[3688465])
    nombre: str = Field(examples=["Bucaramanga"])
    departamento: str | None = Field(default=None, description="Primer nivel administrativo", examples=["Santander"])
    pais: str | None = Field(default=None, examples=["Colombia"])
    codigo_pais: str | None = Field(default=None, examples=["CO"])
    latitud: float = Field(examples=[7.125])
    longitud: float = Field(examples=[-73.11895])
    poblacion: int | None = Field(default=None, examples=[581130])


class ClimaActual(BaseModel):
    hora: datetime = Field(description="Hora local de la ciudad, sin zona", examples=["2026-10-23T13:00"])
    temperatura_c: float = Field(examples=[28.6])
    humedad_pct: float = Field(examples=[57])
    codigo_tiempo: int = Field(description="Código WMO, p. ej. 3 = nublado, 51 = llovizna (E12)", examples=[3])
    viento_kmh: float = Field(examples=[7.5])


class DiaPronostico(BaseModel):
    """Un día del pronóstico. Open-Meteo puede dejar un valor en null si no lo tiene."""

    fecha: date = Field(examples=["2026-10-23"])
    maxima_c: float | None = Field(examples=[28.7])
    minima_c: float | None = Field(examples=[21.0])
    prob_lluvia_pct: float | None = Field(examples=[84])


class RespuestaClima(BaseModel):
    ciudad: Ciudad
    zona_horaria: str = Field(examples=["America/Bogota"])
    actual: ClimaActual
    dias: list[DiaPronostico]


# Alertas (HU4) ───────────────────────────────────────────────────────────────────


class Objetivo(BaseModel):
    # El id de una ciudad es un número y el de un sensor un texto («S-001»); los dos se
    # guardan como texto para que 3688465 y "3688465" sean el mismo cuerpo (D25).
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    tipo: Literal["ciudad", "sensor"]
    id: str = Field(min_length=1, max_length=64, examples=["3688465"])


class NuevaAlerta(BaseModel):
    """Un umbral registrado: solo se guarda, no se evalúa (D24)."""

    model_config = ConfigDict(extra="forbid")

    objetivo: Objetivo
    variable: Literal["temperatura", "humedad", "viento", "prob_lluvia", "ruido", "co2"]
    condicion: Literal["mayor_que", "menor_que"]
    umbral: float = Field(allow_inf_nan=False, examples=[30])


class Alerta(NuevaAlerta):
    id: str = Field(examples=["a-0001"])
    creada: datetime = Field(description="UTC")


# Sensores ─────────────────────────────────────────────────────────────────────────


class Lectura(BaseModel):
    valor: float = Field(examples=[24.3])
    unidad: str = Field(examples=["°C"])
    marca_tiempo: datetime


class SensorConLectura(BaseModel):
    id: str = Field(examples=["S-001"])
    tipo: str = Field(examples=["temperatura"])
    ubicacion: str = Field(examples=["Edificio A"])
    lectura: Lectura | None = Field(description="null si no se pudo leer; el porqué va en `motivo`")
    motivo: str | None = Field(default=None, examples=["sin respuesta (503)"])


class RespuestaSensores(BaseModel):
    """Todos los sensores con su lectura, aunque el servicio falle (D15, D21)."""

    sensores: list[SensorConLectura]
    completo: bool = Field(description="false si faltó alguna página o alguna lectura")
    motivo: str | None = Field(default=None, examples=["3 de 23 sensores sin lectura"])


# Respuestas del servicio inestable: se validan antes de usarlas (Parte A del enunciado).


class SensorServicio(BaseModel):
    id: str
    tipo: str
    ubicacion: str


class PaginaSensores(BaseModel):
    sensores: list[SensorServicio]
    siguiente: str | None


class LecturaServicio(BaseModel):
    sensor_id: str
    tipo: str
    valor: float
    unidad: str
    marca_tiempo: datetime


# Parte E: libros de la API del grupo de Open Library (D44, D45) ──────────────────


class Libro(BaseModel):
    """Una obra y su autor, con los mismos campos y nombres del `ResumenObra` de su
    contrato: así quien lea su OpenAPI reconoce la respuesta."""

    obra: str = Field(examples=["Cien años de soledad"])
    autor: str = Field(examples=["Gabriel García Márquez"])
    clave_autor: str = Field(description="Clave del autor en Open Library", examples=["OL27363A"])
    nombre_personal_real: str | None = Field(default=None, examples=["García Márquez, Gabriel"])
    fecha_nacimiento: str | None = Field(
        default=None, description="Texto tal como lo da su API; su contrato no fija el formato", examples=["1927-03-06"]
    )
