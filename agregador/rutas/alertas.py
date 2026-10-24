"""Alertas de umbral: crear sin duplicados, listar y traer una (HU4; D24, D25).

Una alerta solo se guarda, no se evalúa, y vive en memoria: se pierde al reiniciar el
contenedor (D24). No tiene dependencias externas, así que la idempotencia se demuestra
sin el ruido de los fallos.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from agregador.idempotencia import ClaveEnCurso, ClaveReutilizada, RespuestaGuardada, huella
from agregador.modelos import Alerta, NuevaAlerta

router = APIRouter(prefix="/v1", tags=["alertas"])

LARGO_MAXIMO_CLAVE = 255


class RegistroAlertas:
    """Las alertas creadas, con ids secuenciales a-0001, a-0002… (detalle 3 del canvas)."""

    def __init__(self) -> None:
        self._alertas: dict[str, Alerta] = {}

    def crear(self, nueva: NuevaAlerta) -> Alerta:
        alerta = Alerta(
            **nueva.model_dump(), id=f"a-{len(self._alertas) + 1:04d}", creada=datetime.now(timezone.utc)
        )
        self._alertas[alerta.id] = alerta
        return alerta

    def todas(self) -> list[Alerta]:
        return list(self._alertas.values())

    def traer(self, id_alerta: str) -> Alerta | None:
        return self._alertas.get(id_alerta)


def _error(detalle: str) -> dict:
    return {"description": detalle, "content": {"application/json": {"example": {"detail": detalle}}}}


@router.post(
    "/alertas",
    status_code=201,
    summary="Crear una alerta de umbral, sin duplicados",
    description=(
        "Requiere `Idempotency-Key` (D25). Repetir la petición con la misma clave y el mismo cuerpo "
        "devuelve la misma respuesta (el mismo id y 201) sin crear otra alerta. La clave dura 24 h."
    ),
    responses={
        201: {"headers": {"Location": {"description": "URL de la alerta creada", "schema": {"type": "string"}}}},
        400: _error("Falta la cabecera Idempotency-Key"),
        409: _error("La primera petición con esta Idempotency-Key todavía está en curso"),
        422: _error("Esta Idempotency-Key ya se usó con otro cuerpo, o el cuerpo no es válido"),
    },
)
async def crear_alerta(
    request: Request,
    nueva: NuevaAlerta,
    # Opcional para FastAPI, obligatoria para nosotros: si FastAPI la exigiera, su
    # ausencia sería un 422, y D25 pide 400.
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Obligatoria. Un valor único por alerta, p. ej. un UUID; se reutiliza al reintentar",
        ),
    ] = None,
) -> Alerta:
    clave = (idempotency_key or "").strip()
    if not clave:
        raise HTTPException(400, "Falta la cabecera Idempotency-Key")
    if len(clave) > LARGO_MAXIMO_CLAVE:
        raise HTTPException(400, f"La Idempotency-Key no puede pasar de {LARGO_MAXIMO_CLAVE} caracteres")

    estado = request.app.state

    async def crear() -> RespuestaGuardada:
        alerta = estado.alertas.crear(nueva)
        ubicacion = str(request.url_for("traer_alerta", id=alerta.id).path)
        return RespuestaGuardada(201, alerta.model_dump(mode="json"), {"Location": ubicacion})

    try:
        guardada, _ = await estado.idempotencia.ejecutar(clave, huella(nueva), crear)
    except ClaveReutilizada:
        raise HTTPException(422, "Esta Idempotency-Key ya se usó con otro cuerpo") from None
    except ClaveEnCurso:
        raise HTTPException(409, "La primera petición con esta Idempotency-Key todavía está en curso") from None
    return JSONResponse(guardada.cuerpo, status_code=guardada.codigo, headers=guardada.cabeceras)


@router.get("/alertas", summary="Listar las alertas creadas")
async def listar_alertas(request: Request) -> list[Alerta]:
    return request.app.state.alertas.todas()


@router.get(
    "/alertas/{id}",
    summary="Traer una alerta",
    responses={404: _error("No existe la alerta a-0099")},
)
async def traer_alerta(request: Request, id: str) -> Alerta:
    alerta = request.app.state.alertas.traer(id)
    if alerta is None:
        raise HTTPException(404, f"No existe la alerta {id}")
    return alerta
