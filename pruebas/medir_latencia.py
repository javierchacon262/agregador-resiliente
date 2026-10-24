"""Medición de latencia con caché y sin ella (HU6, D34).

Hace 20 peticiones en frío (con `Cache-Control: no-cache`, que obliga a ir a Open-Meteo)
y 20 en caliente a `GET /v1/ciudades/{id}/clima`, de a una, y escribe la tabla del
README con mediana, p95 y máximo. Mide desde el cliente, que es lo que vería el usuario.

    docker compose run --rm pruebas python pruebas/medir_latencia.py
    docker compose run --rm pruebas python pruebas/medir_latencia.py --id 3688465 --muestras 20

Con 20 muestras el p95 es la segunda peor, y así se debe leer (D34).
"""

import argparse
import math
import os
import statistics
import time

import httpx


def medir(cliente: httpx.Client, ruta: str, muestras: int, cabeceras: dict, esperado: str) -> list[float]:
    tiempos = []
    for _ in range(muestras):
        inicio = time.perf_counter()
        respuesta = cliente.get(ruta, headers=cabeceras)
        tiempos.append((time.perf_counter() - inicio) * 1000)
        respuesta.raise_for_status()
        # Si la caché no hizo lo que se esperaba, la tabla no mide lo que dice.
        estado = respuesta.headers.get("Cache-Status", "")
        if esperado not in estado:
            raise SystemExit(f"Se esperaba «{esperado}» en Cache-Status y llegó «{estado}»")
    return tiempos


def p95(valores: list[float]) -> float:
    # Rango más cercano, igual que en /v1/metricas.
    return sorted(valores)[math.ceil(0.95 * len(valores)) - 1]


def fila(nombre: str, tiempos: list[float]) -> str:
    def ms(valor: float) -> str:
        return f"{valor:,.1f}".replace(",", " ").replace(".", ",")

    return f"| {nombre} | {len(tiempos)} | {ms(statistics.median(tiempos))} | {ms(p95(tiempos))} | {ms(max(tiempos))} |"


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--url", default=os.environ.get("AGREGADOR_URL", "http://agregador:8000"))
    argumentos.add_argument("--id", type=int, default=3688465, help="Ciudad; por defecto Bucaramanga")
    argumentos.add_argument("--dias", type=int, default=7)
    argumentos.add_argument("--muestras", type=int, default=20)
    opciones = argumentos.parse_args()

    ruta = f"/v1/ciudades/{opciones.id}/clima?dias={opciones.dias}"
    with httpx.Client(base_url=opciones.url, timeout=30) as cliente:
        # La primera fría también deja la respuesta guardada para las calientes (D33).
        frias = medir(cliente, ruta, opciones.muestras, {"Cache-Control": "no-cache"}, "fwd=request")
        calientes = medir(cliente, ruta, opciones.muestras, {}, "hit")

    print(f"GET {ruta} · {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC · milisegundos\n")
    print("| Condición | Peticiones | Mediana | p95 | Máximo |")
    print("|---|---|---|---|---|")
    print(fila("Sin caché (`no-cache`)", frias))
    print(fila("Con caché (`hit`)", calientes))
    print(f"\nMejora de la mediana: {statistics.median(frias) / statistics.median(calientes):.0f} veces más rápida")


if __name__ == "__main__":
    main()
