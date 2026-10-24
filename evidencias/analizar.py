"""Comprueba en los logs de evidencias/ que se respetó cada Retry-After.

Cuenta las llegadas reales al servicio inestable y, después de cada 429, mide cuánto
tardó en llegar nuestra siguiente petición. Corre en la imagen del proyecto (D16):

    docker run --rm -v "$PWD/evidencias":/app/evidencias:ro agregador-resiliente:local \
      python evidencias/analizar.py
"""

import re
from datetime import datetime
from pathlib import Path

CARPETA = Path(__file__).parent

PATRON = re.compile(r"\[(\d\d:\d\d:\d\d\.\d{3})\]\s+\S+ GET (\S+) -> (.*)")
lineas = (CARPETA / "servicio-inestable.log").read_text().splitlines()

# Llegadas reales: una lenta deja «lenta» al llegar y su código al responder, segundos
# después; ese segundo renglón no es una llegada.
# El final de una lenta se reconoce por el tiempo: llega justo la latencia después de
# su línea «lenta» (el servicio duerme antes de responder).
llegadas, lentas = [], {}
for l in lineas:
    m = PATRON.match(l)
    if not m:
        continue
    t, ruta, resultado = datetime.strptime(m.group(1), "%H:%M:%S.%f"), m.group(2), m.group(3)
    if resultado.startswith("lenta"):
        duracion = float(re.search(r"lenta \(([\d.]+) s\)", resultado).group(1))
        lentas.setdefault(ruta, []).append(t.timestamp() + duracion)
        llegadas.append((t, l))
        continue
    fin = next((f for f in lentas.get(ruta, []) if abs(t.timestamp() - f) < 0.05), None)
    if fin is not None:
        lentas[ruta].remove(fin)  # es la respuesta de una lenta, no una llegada nueva
    else:
        llegadas.append((t, l))

huecos = []
for i, (t, l) in enumerate(llegadas):
    if "429 (Retry-After" in l and i + 1 < len(llegadas):
        huecos.append(((llegadas[i + 1][0] - t).total_seconds(), l, llegadas[i + 1][1]))
print("llegadas:", len(llegadas), "· 429 emitidos:", len(huecos), "· no respetó:", sum("no respetó" in l for l in lineas))
print("tras un 429, la siguiente llegada fue a los: mín %.3f s · máx %.3f s" % (min(h[0] for h in huecos), max(h[0] for h in huecos)))
h = min(huecos)
print("el caso más justo:\n  ", h[1].strip(), "\n  ", h[2].strip())
