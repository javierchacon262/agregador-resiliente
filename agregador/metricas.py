"""Contadores para `GET /v1/metricas` y el panel de resiliencia del dashboard (D35).

Viven en memoria desde el arranque, así que se pierden al reiniciar el contenedor.
"""

import math
import statistics
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone

DEPENDENCIAS = ("servicio_inestable", "open_meteo", "otro_grupo")
VENTANA_LATENCIAS = 100  # últimas peticiones por ruta (detalle 10 del canvas)


class RegistroMetricas:
    def __init__(self) -> None:
        self.desde = datetime.now(timezone.utc)
        self._llamadas = Counter()  # dependencia → llamadas lógicas
        self._resultados = {d: Counter() for d in DEPENDENCIAS}  # dependencia → resultado → intentos
        self._errores = {d: Counter() for d in DEPENDENCIAS}  # dependencia → 502/504 → respuestas
        self._cache = Counter()
        self._latencias: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=VENTANA_LATENCIAS))

    def registrar_llamada(self, dependencia: str) -> None:
        self._llamadas[dependencia] += 1

    def registrar_intento(self, dependencia: str, resultado: str) -> None:
        """`resultado` es el código («200», «503»…) o la causa («timeout», «conexion», «plazo»)."""
        self._resultados[dependencia][resultado] += 1

    def registrar_error_dependencia(self, dependencia: str, codigo: int) -> None:
        self._errores[dependencia][codigo] += 1

    def registrar_cache(self, acierto: bool) -> None:
        self._cache["aciertos" if acierto else "fallos"] += 1

    def registrar_latencia(self, ruta: str, segundos: float) -> None:
        self._latencias[ruta].append(segundos)

    def instantanea(self, compuerta_cerrada_hasta: datetime | None = None) -> dict:
        dependencias = {}
        for dependencia in DEPENDENCIAS:
            resultados = self._resultados[dependencia]
            intentos = sum(resultados.values())
            dependencias[dependencia] = {
                "llamadas": self._llamadas[dependencia],
                "intentos": intentos,
                # Cada intento de más sobre la primera llamada es un reintento.
                "reintentos": intentos - self._llamadas[dependencia],
                "por_resultado": dict(sorted(resultados.items())),
                "respuestas_502": self._errores[dependencia][502],
                "respuestas_504": self._errores[dependencia][504],
            }
        dependencias["servicio_inestable"]["compuerta_cerrada_hasta"] = compuerta_cerrada_hasta
        return {
            "desde": self.desde,
            "dependencias": dependencias,
            "cache": {"aciertos": self._cache["aciertos"], "fallos": self._cache["fallos"]},
            "latencia_ms": {ruta: _resumen(valores) for ruta, valores in sorted(self._latencias.items())},
        }


def _resumen(segundos: deque[float]) -> dict:
    ordenados = sorted(segundos)
    # p95 por rango más cercano: con 20 muestras es la segunda peor (D34).
    p95 = ordenados[math.ceil(0.95 * len(ordenados)) - 1]
    return {
        "peticiones": len(ordenados),
        "mediana": round(statistics.median(ordenados) * 1000, 1),
        "p95": round(p95 * 1000, 1),
    }
