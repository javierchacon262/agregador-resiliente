"""Pruebas unitarias de los reintentos (D12), sin red ni esperas de verdad.

Un servidor falso (httpx.MockTransport) responde un guion de resultados, y un reloj
falso avanza solo cuando el código «duerme». Cada prueba dice qué regla demuestra.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from agregador.resiliencia import (
    CompuertaRetryAfter,
    ErrorDependencia,
    Politica,
    calcular_espera,
    es_reintentable,
    leer_retry_after,
    llamar_con_reintentos,
    timeout_para,
)

POLITICA = Politica(
    dependencia="servicio_inestable",
    etiqueta="sensores",
    maximo=6,
    timeouts_lectura=(3, 6, 8),
    timeout_conexion=2,
    base=0.5,
    tope=8,
)


class RelojFalso:
    """Avanza solo cuando el código duerme, así las pruebas no esperan de verdad."""

    def __init__(self) -> None:
        self.ahora = 0.0

    def __call__(self) -> float:
        return self.ahora

    async def dormir(self, segundos: float) -> None:
        self.ahora += max(0.0, segundos)


class ServidorFalso:
    """Responde los pasos del guion en orden y anota cuándo llegó cada petición."""

    def __init__(self, reloj: RelojFalso, *pasos) -> None:
        self.reloj = reloj
        self.pasos = list(pasos)
        self.llegadas: list[float] = []

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.llegadas.append(self.reloj())
        paso = self.pasos.pop(0)
        if isinstance(paso, Exception):
            raise paso
        codigo, cabeceras = paso if isinstance(paso, tuple) else (paso, {})
        return httpx.Response(codigo, headers=cabeceras, json={})


def llamar(servidor: ServidorFalso, *, compuerta=None, fecha_limite: float = 45.0, politica=POLITICA):
    reloj = servidor.reloj

    async def correr():
        transporte = httpx.MockTransport(servidor)
        async with httpx.AsyncClient(transport=transporte, base_url="http://servicio") as cliente:
            return await llamar_con_reintentos(
                cliente,
                "GET",
                "/sensores",
                politica=politica,
                fecha_limite=fecha_limite,
                compuerta=compuerta,
                reloj=reloj,
                dormir=reloj.dormir,
                azar=lambda minimo, maximo: maximo,  # el peor caso del jitter, para que sea predecible
            )

    return asyncio.run(correr())


# 1 · es_reintentable ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("codigo", [429, 503])
def test_reintenta_429_y_503(codigo):
    assert es_reintentable(httpx.Response(codigo))


@pytest.mark.parametrize("codigo", [200, 400, 404, 422, 500])
def test_no_reintenta_lo_definitivo(codigo):
    assert not es_reintentable(httpx.Response(codigo))


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("lenta"), httpx.ConnectTimeout("lenta"), httpx.ConnectError("caído")]
)
def test_reintenta_timeouts_y_conexion_caida(error):
    assert es_reintentable(error)


def test_no_reintenta_una_url_mal_formada():
    assert not es_reintentable(httpx.UnsupportedProtocol("sin esquema"))


# 2 · leer_retry_after ────────────────────────────────────────────────────────────


def test_retry_after_en_segundos():
    assert leer_retry_after(httpx.Response(429, headers={"Retry-After": "2"})) == 2.0


def test_retry_after_como_fecha_http():
    fecha = datetime.now(timezone.utc) + timedelta(seconds=30)
    segundos = leer_retry_after(httpx.Response(429, headers={"Retry-After": format_datetime(fecha, usegmt=True)}))
    assert 28 <= segundos <= 30


@pytest.mark.parametrize("cabeceras", [{}, {"Retry-After": "pronto"}, {"Retry-After": "-3"}])
def test_retry_after_ausente_o_invalido_se_ignora(cabeceras):
    assert leer_retry_after(httpx.Response(429, headers=cabeceras)) is None


# 3 · calcular_espera ─────────────────────────────────────────────────────────────


def test_backoff_exponencial_con_tope():
    peor_caso = [calcular_espera(i, None, 0.5, 8, azar=lambda a, b: b) for i in range(6)]
    assert peor_caso == [0.5, 1, 2, 4, 8, 8]


def test_el_jitter_elige_al_azar_entre_cero_y_el_techo():
    assert calcular_espera(3, None, 0.5, 8, azar=lambda a, b: a) == 0


def test_nunca_vuelve_antes_del_retry_after():
    assert calcular_espera(0, 2.0, 0.5, 8, azar=lambda a, b: a) == 2.0


# 4 · timeout_para ────────────────────────────────────────────────────────────────


def test_timeouts_adaptativos():
    assert [timeout_para(i, (3, 6, 8)) for i in range(5)] == [3, 6, 8, 8, 8]


# 5 · CompuertaRetryAfter ─────────────────────────────────────────────────────────


def test_la_compuerta_conserva_el_cierre_mas_largo():
    compuerta = CompuertaRetryAfter(reloj=RelojFalso())
    compuerta.cerrar_hasta(5)
    compuerta.cerrar_hasta(2)
    assert compuerta.hasta == 5


def test_un_429_cierra_la_compuerta_para_todos():
    reloj = RelojFalso()
    compuerta = CompuertaRetryAfter(reloj=reloj, dormir=reloj.dormir)
    llamar(ServidorFalso(reloj, (429, {"Retry-After": "2"}), 200), compuerta=compuerta)
    assert compuerta.hasta == 2.0


def test_otra_llamada_espera_a_que_abra_la_compuerta():
    reloj = RelojFalso()
    compuerta = CompuertaRetryAfter(reloj=reloj, dormir=reloj.dormir)
    compuerta.cerrar_hasta(5.0)  # como si otra llamada en vuelo hubiera recibido un 429
    servidor = ServidorFalso(reloj, 200)
    llamar(servidor, compuerta=compuerta)
    assert servidor.llegadas == [5.0]


def test_el_turno_de_envio_no_deja_salir_otra_llamada_antes_de_saber_del_429():
    # Dos llamadas a la vez y una respuesta que tarda en llegar: sin el turno, la
    # segunda saldría mientras el 429 de la primera viene en camino, y el servicio la
    # registraría como «no respetó Retry-After» (C8).
    reloj = RelojFalso()
    compuerta = CompuertaRetryAfter(reloj=reloj, dormir=reloj.dormir)
    guion = [(429, {"Retry-After": "2"}), (200, {}), (200, {})]
    llegadas = []

    async def responder(peticion: httpx.Request) -> httpx.Response:
        llegadas.append(reloj())
        codigo, cabeceras = guion.pop(0)
        await asyncio.sleep(0.01)  # la respuesta tarda 10 ms: tiempo de sobra para que salga la otra
        return httpx.Response(codigo, headers=cabeceras, json={})

    async def correr():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder), base_url="http://servicio") as cliente:

            def llamada():
                return llamar_con_reintentos(
                    cliente, "GET", "/sensores", politica=POLITICA, fecha_limite=45.0,
                    compuerta=compuerta, reloj=reloj, dormir=reloj.dormir, azar=lambda a, b: b,
                )

            await asyncio.gather(llamada(), llamada())

    asyncio.run(correr())
    assert llegadas[0] == 0.0
    assert all(llegada >= 2.0 for llegada in llegadas[1:])


def test_no_espera_una_compuerta_que_abre_despues_del_plazo():
    reloj = RelojFalso()
    compuerta = CompuertaRetryAfter(reloj=reloj, dormir=reloj.dormir)
    compuerta.cerrar_hasta(50.0)
    servidor = ServidorFalso(reloj, 200)
    with pytest.raises(ErrorDependencia) as error:
        llamar(servidor, compuerta=compuerta, fecha_limite=45.0)
    assert (error.value.codigo, error.value.causa) == (504, "plazo")
    assert servidor.llegadas == []


# 6 · llamar_con_reintentos ───────────────────────────────────────────────────────


def test_503_y_despues_200():
    servidor = ServidorFalso(RelojFalso(), 503, 200)
    assert llamar(servidor).status_code == 200
    assert len(servidor.llegadas) == 2


def test_respeta_retry_after():
    servidor = ServidorFalso(RelojFalso(), (429, {"Retry-After": "2"}), 200)
    llamar(servidor)
    assert servidor.llegadas[1] - servidor.llegadas[0] >= 2


@pytest.mark.parametrize("codigo", [400, 404])
def test_400_y_404_no_se_reintentan(codigo):
    servidor = ServidorFalso(RelojFalso(), codigo)
    assert llamar(servidor).status_code == codigo
    assert len(servidor.llegadas) == 1


def test_una_conexion_caida_se_reintenta():
    servidor = ServidorFalso(RelojFalso(), httpx.ConnectError("caído"), 200)
    assert llamar(servidor).status_code == 200


def test_timeouts_agotados_dan_504():
    servidor = ServidorFalso(RelojFalso(), *[httpx.ReadTimeout("lenta")] * 6)
    with pytest.raises(ErrorDependencia) as error:
        llamar(servidor)
    assert (error.value.codigo, error.value.causa, error.value.intentos) == (504, "timeout", 6)


def test_503_agotados_dan_502():
    servidor = ServidorFalso(RelojFalso(), *[503] * 6)
    with pytest.raises(ErrorDependencia) as error:
        llamar(servidor)
    assert (error.value.codigo, error.value.causa, error.value.intentos) == (502, "503", 6)


def test_plazo_agotado_da_504():
    # Peor caso del jitter: espera 0,5 s tras el 1.er intento y 1 s tras el 2.º, que ya
    # pasaría del plazo de 1 s: se rinde sin dormir.
    servidor = ServidorFalso(RelojFalso(), 503, 503, 503)
    with pytest.raises(ErrorDependencia) as error:
        llamar(servidor, fecha_limite=1.0)
    assert (error.value.codigo, error.value.causa) == (504, "plazo")
    assert len(servidor.llegadas) == 2


def test_otro_5xx_no_se_reintenta_y_da_502():
    servidor = ServidorFalso(RelojFalso(), 500)
    with pytest.raises(ErrorDependencia) as error:
        llamar(servidor)
    assert (error.value.codigo, error.value.causa) == (502, "500")
    assert len(servidor.llegadas) == 1


def test_deja_una_linea_de_evidencia_por_intento(capsys):
    llamar(ServidorFalso(RelojFalso(), (429, {"Retry-After": "2"}), 200))
    lineas = capsys.readouterr().out.splitlines()
    assert "sensores 1/6 GET /sensores -> 429 (0 ms) · Retry-After 2 s · espera 2,00 s" in lineas[0]
    assert "sensores 2/6 GET /sensores -> 200 (0 ms)" in lineas[1]
