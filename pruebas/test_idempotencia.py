"""Pruebas unitarias del almacén de idempotencia (D25), sin red.

Cada prueba dice qué regla demuestra. El 409 solo se puede provocar aquí: en la API la
creación de una alerta no espera nada, así que termina antes de que llegue otra
petición.
"""

import asyncio

import pytest

from agregador.idempotencia import (
    AlmacenIdempotencia,
    ClaveEnCurso,
    ClaveReutilizada,
    RespuestaGuardada,
    huella,
)
from agregador.modelos import NuevaAlerta


class RelojFalso:
    def __init__(self) -> None:
        self.ahora = 0.0

    def __call__(self) -> float:
        return self.ahora


class Creador:
    """Hace de la creación de una alerta: cuenta cuántas se crearon de verdad."""

    def __init__(self) -> None:
        self.creadas = 0

    async def __call__(self) -> RespuestaGuardada:
        self.creadas += 1
        return RespuestaGuardada(201, {"id": f"a-{self.creadas:04d}"}, {"Location": f"/v1/alertas/a-{self.creadas:04d}"})


def alerta(**cambios) -> NuevaAlerta:
    cuerpo = {"objetivo": {"tipo": "ciudad", "id": 3688465}, "variable": "temperatura", "condicion": "mayor_que", "umbral": 30}
    return NuevaAlerta.model_validate(cuerpo | cambios)


@pytest.fixture
def reloj():
    return RelojFalso()


@pytest.fixture
def almacen(reloj):
    return AlmacenIdempotencia(ttl=86400, reloj=reloj)


def test_misma_clave_y_mismo_cuerpo_crean_una_sola_alerta(almacen):
    """Parte D.1 del enunciado: dos peticiones, una alerta, la misma respuesta."""
    crear = Creador()
    primera, repetida = asyncio.run(almacen.ejecutar("k", huella(alerta()), crear))
    segunda, repetida_2 = asyncio.run(almacen.ejecutar("k", huella(alerta()), crear))
    assert crear.creadas == 1
    assert primera == segunda
    assert (repetida, repetida_2) == (False, True)


def test_claves_distintas_crean_alertas_distintas(almacen):
    """Una segunda alerta igual hecha a propósito lleva otra clave, y se crea."""
    crear = Creador()
    asyncio.run(almacen.ejecutar("k1", huella(alerta()), crear))
    asyncio.run(almacen.ejecutar("k2", huella(alerta()), crear))
    assert crear.creadas == 2


def test_misma_clave_con_otro_cuerpo_es_422(almacen):
    crear = Creador()
    asyncio.run(almacen.ejecutar("k", huella(alerta()), crear))
    with pytest.raises(ClaveReutilizada):
        asyncio.run(almacen.ejecutar("k", huella(alerta(umbral=35)), crear))
    assert crear.creadas == 1


def test_misma_clave_con_la_primera_en_curso_es_409(almacen):
    """El reintento llega mientras la primera todavía no responde."""

    async def escenario():
        soltar = asyncio.Event()

        async def lenta():
            await soltar.wait()
            return RespuestaGuardada(201, {"id": "a-0001"}, {})

        primera = asyncio.create_task(almacen.ejecutar("k", huella(alerta()), lenta))
        await asyncio.sleep(0)  # la primera ya registró la clave y está esperando
        with pytest.raises(ClaveEnCurso):
            await almacen.ejecutar("k", huella(alerta()), lenta)
        soltar.set()
        respuesta, _ = await primera
        # Cuando termina, el reintento ya recibe la respuesta guardada.
        assert await almacen.ejecutar("k", huella(alerta()), lenta) == (respuesta, True)

    asyncio.run(escenario())


def test_si_la_creacion_falla_la_clave_queda_libre(almacen):
    """No hay respuesta que repetir: el cliente puede reintentar con la misma clave."""

    async def falla():
        raise RuntimeError("se cayó")

    with pytest.raises(RuntimeError):
        asyncio.run(almacen.ejecutar("k", huella(alerta()), falla))
    crear = Creador()
    asyncio.run(almacen.ejecutar("k", huella(alerta()), crear))
    assert crear.creadas == 1


def test_la_clave_se_olvida_a_las_24_horas(almacen, reloj):
    crear = Creador()
    asyncio.run(almacen.ejecutar("k", huella(alerta()), crear))
    reloj.ahora += 86399
    asyncio.run(almacen.ejecutar("k", huella(alerta()), crear))
    assert crear.creadas == 1
    reloj.ahora += 1
    # Vencida, hasta un cuerpo distinto se acepta: es una clave nueva.
    asyncio.run(almacen.ejecutar("k", huella(alerta(umbral=35)), crear))
    assert crear.creadas == 2


def test_la_huella_no_cambia_por_la_forma_del_json():
    """Detalle 5 del canvas: 30 y 30.0, un id numérico o en texto, y el orden de los
    campos no cambian la huella; un umbral distinto sí."""
    a = NuevaAlerta.model_validate_json(
        '{"objetivo":{"tipo":"ciudad","id":3688465},"variable":"temperatura","condicion":"mayor_que","umbral":30}'
    )
    b = NuevaAlerta.model_validate_json(
        '{"umbral":30.0,"condicion":"mayor_que","variable":"temperatura","objetivo":{"id":"3688465","tipo":"ciudad"}}'
    )
    assert huella(a) == huella(b)
    assert huella(a) != huella(alerta(umbral=30.5))
