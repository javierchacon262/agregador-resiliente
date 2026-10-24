# Reporte de pruebas: Open-Meteo, caché, ciudades y alertas (tareas 10–15)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-23 |
| Rama | `feat/ciudades-alertas-y-pruebas`, sobre `main` en `7c5b4cd` |
| Autora | Maria Fernanda Ruiz Velasquez |
| Entorno | Docker 29.8.1 (Docker Desktop, macOS), imagen del `Dockerfile` (Python 3.12.15), Open-Meteo real |
| Resultado | **118 pruebas en verde**, 0 fallas, con los parámetros por defecto y con los del enunciado |

## Cómo se corrió

Todo dentro de Docker (D16, D23), desde la imagen recién construida:

```bash
docker compose up -d --build --wait
docker compose run --rm pruebas                                    # la colección completa
docker compose run --rm --no-deps -e AGREGADOR_URL= pruebas        # solo las que no necesitan el stack
TASA_FALLOS=0.4 LATENCIA=5 docker compose up -d --wait && docker compose run --rm pruebas
docker compose run --rm pruebas python pruebas/medir_latencia.py   # tabla de latencias
```

## Resultados

| Archivo | Pruebas | Tipo | Resultado |
|---|---|---|---|
| `test_resiliencia.py` (tareas 5–6, Javier) | 34 | Unitarias, sin red | 34 en verde |
| `test_cache.py` | 14 | Unitarias, reloj falso | 14 en verde |
| `test_idempotencia.py` | 7 | Unitarias, reloj falso | 7 en verde |
| `test_open_meteo.py` | 16 | Unitarias, Open-Meteo falso con `MockTransport` | 16 en verde |
| `test_rutas.py` | 32 | La app de verdad con un Open-Meteo falso | 32 en verde |
| `test_api_ciudades.py` | 8 | Colección: stack y Open-Meteo real | 8 en verde |
| `test_api_alertas.py` | 7 | Colección: stack | 7 en verde |
| **Total** | **118** | | **118 en verde** (84 nuevas) |

| Escenario | Resultado |
|---|---|
| Parámetros por defecto del servicio inestable | 118 en verde (4,06 s) |
| `TASA_FALLOS=0.4 LATENCIA=5`, los del enunciado (verificados en `/config`) | 118 en verde (2,66 s) |
| Sin stack (`--no-deps -e AGREGADOR_URL=`) | 103 en verde y 15 saltadas, las de la colección |

Hoy ninguna de estas pruebas pasa por el servicio inestable: los sensores son las tareas
7–9. La corrida con los parámetros del enunciado comprueba que la configuración no
afecta a las rutas de ciudades y alertas.

## Qué cubre cada criterio

| Criterio (historia o decisión) | Dónde se prueba |
|---|---|
| HU1: candidatos con departamento y país; `pais` en mayúsculas | `test_rutas`, `test_api_ciudades`, `test_open_meteo` |
| HU1 y D36: sin coincidencias → 200 `[]`; `results` ausente (E1) | `test_rutas`, `test_api_ciudades`, `test_open_meteo` |
| HU1 y HU2: 422 **antes** de llamar a Open-Meteo (nombre corto, país, días, id) | `test_rutas`, que verifica que no hubo ninguna petición |
| HU2 y D07: `get` y después `forecast`, en ese orden | `test_rutas::test_clima_encadena_ficha_y_pronostico` |
| HU2 y E6: id inexistente → 404 sin reintentar; otro 400 → 502 | `test_open_meteo`, `test_rutas`, `test_api_ciudades` |
| HU2 y E7: listas paralelas juntadas por día; si el largo no coincide → 502 | `test_open_meteo` |
| D20 y D22: 3 intentos; 503 agotados → 502; timeouts → 504; conexión caída se reintenta; 429 sin compuerta | `test_open_meteo`, `test_rutas` |
| D32 y D33: TTL de 24 h y 15 min, `no-cache` y los cuatro `Cache-Status` | `test_cache`, `test_rutas`, `test_api_ciudades` |
| Un 502 no queda en la caché | `test_cache`, `test_rutas` |
| D24 y D25: 201 con `Location`; 400, 422 y 409; la misma respuesta repetida; vence a las 24 h | `test_idempotencia`, `test_rutas`, `test_api_alertas` |
| Detalle 5 del canvas: `30` y `30.0` son el mismo cuerpo | `test_idempotencia`, `test_rutas` |
| D35: aciertos y fallos de caché en `/v1/metricas` | `test_cache`, `test_api_ciudades` |
| Parte B.4: `/docs` documenta 404/422/502/504, `Cache-Status` e `Idempotency-Key` | `test_rutas::test_las_rutas_aparecen_en_el_contrato_openapi` |

## Las pruebas detectan errores de verdad

Para confirmar que una prueba en verde significa algo, se rompió el código a propósito
tres veces y se volvieron a correr:

| Error introducido | ¿Lo detectan? |
|---|---|
| La caché ignora `Cache-Control: no-cache` | Sí: fallan 3 pruebas de `test_cache` y `test_rutas` |
| Todo 400 de la ficha se toma como «no existe» | Sí: falla `test_otro_400_de_la_ficha_no_es_404` |
| La huella de idempotencia no ordena las claves | No, y es correcto: `model_dump` ya entrega los campos en el orden del modelo, así que ordenarlos no cambia nada. Se deja como protección |

## Pruebas manuales y depuración

Con `curl` contra el stack, además de la colección:

- Búsqueda, clima, 404, 422 y la secuencia `uri-miss` → `hit` → `request` de
  `Cache-Status`, con sus líneas en `docker compose logs agregador`.
- **Open-Meteo caído de verdad:** un agregador aparte apuntado a un puerto cerrado
  responde **502** `conexion` después de 3 intentos con jitter, en 1,24 s. Apuntado a
  una IP que no responde, termina en **502** en 4,22 s. En Docker Desktop esa IP a
  veces rechaza en lugar de no responder, así que el último intento fue de conexión
  y no un timeout, y D20 da 502. Los dos casos quedan dentro del plazo de 15 s (D18).
- Idempotencia con `curl`: es la salida que está en la sección «Demostración de
  idempotencia» del README.

Lo que se ajustó al depurar:

- El primer diseño usaba un `asyncio.Lock` por clave, pero nunca se esperaba: el 409 lo
  decide si la clave ya tiene respuesta. Se quitó, y el registro «en curso» hace de
  candado. Como en asyncio no hay `await` entre buscar la clave y registrarla, la
  exclusión no cambia. Queda anotado en «Cambios» del canvas.
- Se aceptan valores diarios `null` de Open-Meteo, para no responder 502 por un día
  sin dato. Hoy no llegan nulos a 16 días, pero el modelo lo permite.
- Un país inexistente con formato ISO-2 (`ZZ`) pasa nuestra validación, y Open-Meteo
  responde 200 sin resultados. Se dejó así: el resultado es una lista vacía, como en
  cualquier búsqueda sin coincidencias (D36).

## Latencia (D34)

| Condición | Peticiones | Mediana (ms) | p95 (ms) | Máximo (ms) |
|---|---|---|---|---|
| Sin caché (`no-cache`) | 20 | 430,5 | 645,3 | 1 737,9 |
| Con caché (`hit`) | 20 | 1,0 | 2,0 | 2,5 |

`GET /v1/ciudades/3688465/clima?dias=7`, 2026-10-23 a las 18:15 UTC. El script falla si
`Cache-Status` no dice lo esperado, así que cada tanda mide lo que su fila dice.

## Lo que queda fuera o abierto

- **Sensores (tareas 7–9, Javier):** `GET /v1/sensores`, su colección y las evidencias
  contra el log del servicio inestable.
- **El 409 solo se prueba en unitarias:** crear una alerta no espera nada, así que dos
  peticiones HTTP nunca se solapan.
- **La colección depende de Open-Meteo real:** `test_api_ciudades` afirma resultados
  concretos (Bucaramanga, San José). Si Open-Meteo falla durante la revisión, esas
  pruebas fallan con 502/504, que es justo lo que debe responder el agregador.
- **Aviso de Starlette:** `TestClient` avisa que usar `httpx` con él está obsoleto. No
  afecta a las pruebas; no se cambió `requirements.txt`, que es de la tarea 1.
