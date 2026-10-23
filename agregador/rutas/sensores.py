"""GET /v1/sensores: todos los sensores con su lectura, aunque el servicio falle (HU3)."""

import time

from fastapi import APIRouter, Request

from agregador import evidencia
from agregador.clientes.sensores import leer_lecturas, recorrer_paginas
from agregador.modelos import CuerpoErrorDependencia, RespuestaSensores, SensorConLectura
from agregador.resiliencia import ErrorDependencia

router = APIRouter(prefix="/v1", tags=["sensores"])

ERRORES = {
    502: {"model": CuerpoErrorDependencia, "description": "No se obtuvo ningún sensor o ninguna lectura (D21)"},
    504: {"model": CuerpoErrorDependencia, "description": "Lo mismo, por timeout o por el plazo de 45 s (D20)"},
}


@router.get(
    "/sensores",
    summary="Todos los sensores con su lectura actual, tolerando fallos del servicio",
    responses=ERRORES,
)
async def listar_sensores(request: Request) -> RespuestaSensores:
    """Recorre todas las páginas y pide cada lectura, con reintentos (D12, D17–D19), la
    compuerta de Retry-After (D14) y un plazo de 45 s para toda la petición (D18).

    Si falta algo, responde 200 con lo obtenido y `completo: false` (D15). Si no obtuvo
    ningún sensor o ninguna lectura, responde 502 o 504 (D20, D21).
    """
    estado = request.app.state
    comunes = dict(
        politica=estado.politica_sensores,
        compuerta=estado.compuerta,
        fecha_limite=time.monotonic() + estado.config.plazo_sensores_s,
        metricas=estado.metricas,
    )
    paginas = await recorrer_paginas(estado.cliente_sensores, **comunes)
    lecturas = await leer_lecturas(
        estado.cliente_sensores,
        [sensor.id for sensor in paginas.sensores],
        concurrencia=estado.config.concurrencia_lecturas,
        **comunes,
    )
    sensores = [
        SensorConLectura(id=s.id, tipo=s.tipo, ubicacion=s.ubicacion, lectura=l.lectura, motivo=l.motivo)
        for s, l in zip(paginas.sensores, lecturas)
    ]

    con_lectura = sum(1 for sensor in sensores if sensor.lectura is not None)
    if con_lectura == 0:
        # D21: sin ningún sensor, o con sensores pero ninguna lectura, se trata como un
        # fallo de la dependencia. Si se acabó el plazo en cualquier parte, es 504; si
        # no, manda la causa del último fallo (D20).
        causas = [c for c in [paginas.causa, *(l.causa for l in lecturas)] if c]
        causa = "plazo" if "plazo" in causas else (causas[-1] if causas else "respuesta_invalida")
        que = "ningún sensor" if not sensores else "ninguna lectura"
        raise ErrorDependencia(
            "servicio_inestable",
            causa,
            evidencia.peticion_actual().intentos,
            f"El servicio inestable no devolvió {que} ({paginas.motivo or causa})",
        )

    motivos = []
    if not paginas.completo:
        motivos.append(paginas.motivo)
    if faltan := len(sensores) - con_lectura:
        motivos.append(f"{faltan} de {len(sensores)} sensores sin lectura")
    completo = not motivos
    evidencia.peticion_actual().nota = "completo" if completo else "incompleto"
    return RespuestaSensores(sensores=sensores, completo=completo, motivo="; ".join(motivos) or None)
