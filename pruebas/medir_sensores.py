"""Mide GET /v1/sensores contra el servicio real, para validar la simulación (tarea 9).

Hace N peticiones seguidas e imprime una fila Markdown con las mismas columnas que las
tablas de la sección 4 del análisis, para compararlas con el modelo:

    docker compose run --rm pruebas python pruebas/medir_sensores.py --peticiones 50 --etiqueta defecto
"""

import argparse
import math
import os
import statistics
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--peticiones", type=int, default=50)
    parser.add_argument("--etiqueta", default="")
    args = parser.parse_args()

    with httpx.Client(base_url=os.environ.get("AGREGADOR_URL", "http://agregador:8000"), timeout=60) as api:
        configuracion = httpx.get(
            os.environ.get("SERVICIO_INESTABLE_URL", "http://servicio-inestable:9000") + "/config", timeout=5
        ).json()
        antes = api.get("/v1/metricas").json()["dependencias"]["servicio_inestable"]["intentos"]
        completas = listas = sin_datos = 0
        duraciones = []
        for _ in range(args.peticiones):
            inicio = time.monotonic()
            respuesta = api.get("/v1/sensores")
            duraciones.append(time.monotonic() - inicio)
            if respuesta.status_code != 200:
                sin_datos += 1
                continue
            cuerpo = respuesta.json()
            completas += cuerpo["completo"]
            # La lista está completa si ninguna página quedó sin respuesta.
            listas += "página" not in (cuerpo["motivo"] or "") and "cursor" not in (cuerpo["motivo"] or "")
        despues = api.get("/v1/metricas").json()["dependencias"]["servicio_inestable"]["intentos"]

    n = args.peticiones
    ordenadas = sorted(duraciones)
    p95 = ordenadas[math.ceil(0.95 * n) - 1]
    pct = lambda cuenta: f"{100 * cuenta / n:.1f} %".replace(".", ",")
    print(f"Servicio: tasa_fallos={configuracion['tasa_fallos']} latencia={configuracion['latencia_s']} · {n} peticiones")
    print("| Servicio | Completa | Lista completa | Sin datos | Mediana | p95 | Máx. | Intentos |")
    print("|---|---|---|---|---|---|---|---|")
    print(
        f"| {args.etiqueta} | {pct(completas)} | {pct(listas)} | {pct(sin_datos)} "
        f"| {statistics.median(ordenadas):.0f} s | {p95:.0f} s | {ordenadas[-1]:.0f} s | {(despues - antes) / n:.0f} |"
    )


if __name__ == "__main__":
    main()
