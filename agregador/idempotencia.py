"""Claves de idempotencia para `POST /v1/alertas` (D25), según el borrador IETF.

Un cliente que pierde la respuesta reintenta con la misma `Idempotency-Key`; la clave
distingue ese reintento de una segunda alerta igual hecha a propósito:

    clave nueva                          → se ejecuta y se guarda la respuesta
    misma clave, mismo cuerpo            → la respuesta guardada, sin ejecutar otra vez
    misma clave, otro cuerpo             → 422: la clave se reutilizó por error
    misma clave, la primera aún en curso → 409: todavía no hay respuesta que repetir

El cuerpo se compara por su huella: SHA-256 del JSON ya validado, con las claves
ordenadas, así `30` y `30.0` cuentan como el mismo cuerpo (detalle 5 del canvas). Las
claves viven en memoria 24 h y se pierden al reiniciar el contenedor.
"""

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

Reloj = Callable[[], float]


@dataclass(frozen=True)
class RespuestaGuardada:
    codigo: int
    cuerpo: dict
    cabeceras: dict[str, str]


@dataclass
class _Registro:
    huella: str
    vence: float
    # None mientras la primera petición se ejecuta: un reintento que llega entonces
    # recibe 409, porque todavía no hay respuesta que repetir.
    respuesta: RespuestaGuardada | None = None


class ClaveEnCurso(Exception):
    """409: la primera petición con esta clave todavía no termina."""


class ClaveReutilizada(Exception):
    """422: la clave ya se usó con otro cuerpo."""


def huella(cuerpo: BaseModel) -> str:
    normalizado = json.dumps(cuerpo.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalizado.encode()).hexdigest()


class AlmacenIdempotencia:
    def __init__(self, ttl: float, reloj: Reloj = time.monotonic):
        self.ttl = ttl
        self._reloj = reloj
        self._registros: dict[str, _Registro] = {}

    def _vigente(self, clave: str) -> _Registro | None:
        registro = self._registros.get(clave)
        if registro is not None and self._reloj() >= registro.vence:
            # Pasadas las 24 h la clave se olvida y se puede volver a usar (D25).
            del self._registros[clave]
            return None
        return registro

    async def ejecutar(
        self, clave: str, huella_cuerpo: str, operacion: Callable[[], Awaitable[RespuestaGuardada]]
    ) -> tuple[RespuestaGuardada, bool]:
        """La respuesta de la operación y si es una repetición (True) o la primera vez.

        Si la operación falla, la clave se libera: no hay respuesta que repetir, y el
        cliente puede reintentar con la misma clave.
        """
        registro = self._vigente(clave)
        if registro is not None:
            if registro.huella != huella_cuerpo:
                raise ClaveReutilizada(clave)
            if registro.respuesta is None:
                raise ClaveEnCurso(clave)
            return registro.respuesta, True

        # Entre buscar la clave y registrarla no hay ningún await, así que en asyncio
        # nadie más puede colarse: el registro en curso hace de candado por clave.
        registro = _Registro(huella=huella_cuerpo, vence=self._reloj() + self.ttl)
        self._registros[clave] = registro
        try:
            registro.respuesta = await operacion()
        except BaseException:
            del self._registros[clave]
            raise
        return registro.respuesta, False

    def __len__(self) -> int:
        return len(self._registros)
