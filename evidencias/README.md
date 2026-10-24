# Evidencias de los reintentos

Los dos logs de una misma corrida, para leerlos lado a lado (D37):

- [`agregador.log`](agregador.log): nuestro log, con una línea por intento y una final
  por petición.
- [`servicio-inestable.log`](servicio-inestable.log): el log del servicio del docente,
  sin modificar, con una línea por petición que le llega.

Corrida del 2026-10-24 con los parámetros del ejemplo del enunciado y semilla fija:
`--tasa-fallos 0.4 --latencia 5 --semilla 42` (la segunda línea del log del servicio
los confirma). Fueron 3 llamadas seguidas a `GET /v1/sensores`. Los dos contenedores
corren en UTC, así que las horas se comparan directamente.

## Resumen

| Qué se ve | Resultado |
|---|---|
| Intentos al servicio | 162, igual en los dos logs |
| Respuestas 429 con Retry-After: 2 | 22 |
| «429 (no respetó Retry-After)» en el log del servicio | **0** |
| Tiempo hasta nuestra siguiente petición después de cada 429 | **mínimo 2,003 s**, máximo 5,94 s |
| Timeouts nuestros por respuestas lentas (5 s), reintentados | 6 |
| Respuestas a `GET /v1/sensores` | una completa y dos con `completo: false` y su motivo (D15) |

Para repetir la comprobación del Retry-After sobre estos logs:

```bash
docker run --rm -v "$PWD/evidencias":/app/evidencias:ro agregador-resiliente:local \
  python evidencias/analizar.py
```

## 1. Un 429 frena a todas nuestras llamadas (D14, D42)

La lectura de S-022 recibe un 429 con Retry-After 2. La compuerta se cierra, y la de
S-021, que iba a salir 80 ms después, espera a que abra. Ninguna petición nuestra
vuelve a llegar al servicio antes de 2 s:

```text
agregador.log
[15:39:52.617] r-0f5b sensores 1/6 GET /sensores/S-022/lectura -> 429 (2 ms) · Retry-After 2 s · espera 2,00 s
[15:39:52.697] r-0f5b sensores 3/6 GET /sensores/S-021/lectura -> espera la compuerta 1,92 s
[15:39:54.621] r-0f5b sensores 3/6 GET /sensores/S-021/lectura -> 429 (3 ms) · Retry-After 2 s · espera 2,00 s

servicio-inestable.log
[15:39:52.616]      172.19.0.2 GET /sensores/S-022/lectura -> 429 (Retry-After: 2)
[15:39:54.620]      172.19.0.2 GET /sensores/S-021/lectura -> 429 (Retry-After: 2)
```

Entre las dos líneas del servicio pasan 2,004 s. La segunda es otro 429 del sorteo, no
un «no respetó».

## 2. Paginación con reintentos selectivos, timeout y backoff con jitter (D12, D19)

Las dos primeras páginas de la primera llamada. Los 503 y el 429 se reintentan, y la
espera cambia en cada intento (jitter). El primer intento corta a los 3 s una respuesta
lenta, y el quinto, con 8 s de margen, la deja terminar (5005 ms):

```text
agregador.log
[15:39:23.373] r-0f5b sensores 1/6 GET /sensores -> timeout (3,02 s) · espera 0,20 s
[15:39:23.579] r-0f5b sensores 2/6 GET /sensores -> 503 (6 ms) · espera 0,08 s
[15:39:23.666] r-0f5b sensores 3/6 GET /sensores -> 503 (3 ms) · espera 1,77 s
[15:39:25.446] r-0f5b sensores 4/6 GET /sensores -> 200 (4 ms)
[15:39:28.448] r-0f5b sensores 1/6 GET /sensores?cursor=bzo1 -> timeout (3,00 s) · espera 0,19 s
[15:39:28.646] r-0f5b sensores 2/6 GET /sensores?cursor=bzo1 -> 503 (6 ms) · espera 0,96 s
[15:39:29.609] r-0f5b sensores 3/6 GET /sensores?cursor=bzo1 -> 429 (3 ms) · Retry-After 2 s · espera 2,00 s
[15:39:31.613] r-0f5b sensores 4/6 GET /sensores?cursor=bzo1 -> 503 (3 ms) · espera 0,55 s
[15:39:37.171] r-0f5b sensores 5/6 GET /sensores?cursor=bzo1 -> 200 (5005 ms)
```

El servicio registra solo la ruta, sin el cursor: por eso en su log todas las páginas
salen como `GET /sensores`. Ahí se ve, además, que una lenta deja dos líneas, «lenta»
al llegar y su código al terminar 5 s después, aunque nosotros ya hayamos cortado y
reintentado (hallazgo S3 del análisis).

## 3. Cuando se agotan los intentos: lo obtenido y el motivo (D15, D17)

En la tercera llamada, la página 3 falla 6 veces. Después de un 429 la espera es de
5,94 s: el jitter de ese intento salió mayor que el Retry-After, y se usa el mayor de
los dos. Sin el cursor de esa página no se pueden pedir las siguientes, así que la
respuesta trae lo obtenido, marcado como incompleto:

```text
agregador.log
[15:40:41.714] r-4121 sensores 1/6 GET /sensores?cursor=bzoxMA%3D%3D -> timeout (3,00 s) · espera 0,27 s
[15:40:41.991] r-4121 sensores 2/6 GET /sensores?cursor=bzoxMA%3D%3D -> 503 (6 ms) · espera 0,08 s
[15:40:42.069] r-4121 sensores 3/6 GET /sensores?cursor=bzoxMA%3D%3D -> 503 (3 ms) · espera 1,69 s
[15:40:43.761] r-4121 sensores 4/6 GET /sensores?cursor=bzoxMA%3D%3D -> 503 (3 ms) · espera 0,12 s
[15:40:43.888] r-4121 sensores 5/6 GET /sensores?cursor=bzoxMA%3D%3D -> 429 (3 ms) · Retry-After 2 s · espera 5,94 s
[15:40:49.829] r-4121 sensores 6/6 GET /sensores?cursor=bzoxMA%3D%3D -> 503 (5 ms) · intentos agotados
[15:40:57.122] r-4121 GET /v1/sensores -> 200 incompleto (20,42 s, 23 intentos)
```

La respuesta dice `"completo": false, "motivo": "la página 3 no respondió (503)"`.

## 4. Las tres respuestas

```text
[15:40:03.567] r-0f5b GET /v1/sensores -> 200 completo (43,22 s, 72 intentos)
[15:40:36.706] r-4e56 GET /v1/sensores -> 200 incompleto (33,14 s, 67 intentos)
[15:40:57.122] r-4121 GET /v1/sensores -> 200 incompleto (20,42 s, 23 intentos)
```

Ninguna pasa del plazo de 45 s (D18).

## Cómo se generaron

```bash
TASA_FALLOS=0.4 LATENCIA=5 SEMILLA=42 docker compose up -d --wait
for i in 1 2 3; do curl -s localhost:8000/v1/sensores > /dev/null; done
docker compose logs --no-log-prefix --no-color agregador > evidencias/agregador.log
docker compose logs --no-log-prefix --no-color servicio-inestable > evidencias/servicio-inestable.log
```

Con varias llamadas a la vez, la semilla fija la secuencia de sorteos del servicio, pero
no quién recibe cada uno (hallazgo S5), así que otra corrida da números parecidos, no
iguales.
