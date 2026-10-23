# AR-001 · Historia: agregador resiliente de clima y sensores

| Campo | Valor |
|---|---|
| ID | AR-001 |
| Tipo | Historia (paso 1 de SPDD) |
| Estado | Borrador revisado en las rondas 1–7 de decisiones; quedan pendientes en el [README](../README.md#decisiones-pendientes) |
| Fecha | 2026-10-17 |
| Fuente | Enunciado «Evaluación-taller: Agregador resiliente de APIs», Sistemas Distribuidos, UIS |

## Problema

El curso pide un servicio en FastAPI que consuma una API pública (elegimos
**Open-Meteo**, [D01](../README.md#log-de-decisiones)) y un servicio que falla a
propósito (`servicio_inestable.py`, del docente), y que exponga una API propia que
siga respondiendo bien aunque esas dependencias fallen. El docente revisa la entrega
ejecutando nuestras peticiones de prueba contra **su propia instancia** del servicio
inestable, con parámetros que no conocemos.

Encima de la API va un dashboard ([D08](../README.md#log-de-decisiones)) que no
suma puntos en la rúbrica, por eso se construye después del backend
([D09](../README.md#log-de-decisiones)).

## Historias

### HU1 · Buscar una ciudad entre candidatos

Como usuario del dashboard quiero escribir el nombre de una ciudad y ver todas las
coincidencias con su departamento y país, para elegir la correcta cuando el nombre
es ambiguo (San José da 10 resultados y el primero es de California).

- `GET /v1/ciudades?nombre={texto}&pais={ISO-2 opcional}` devuelve la lista de
  candidatos: id, nombre, departamento, país, código de país, coordenadas y población.
- `nombre` con menos de 2 caracteres → **422** (Open-Meteo devuelve vacío con 1 letra).
- `pais` que no sea un código ISO-2 → **422**.
- Sin coincidencias → pendiente [P10](../README.md#decisiones-pendientes) (200 con
  lista vacía o 404).
- Las llamadas a Open-Meteo se reintentan con las reglas de HU3, pero con un máximo
  de 3 intentos, sin compuerta y con un plazo de 15 s por petición
  ([D18, D22](../README.md#log-de-decisiones)).
- Open-Meteo no responde o falla → **504** si fue por timeout o se acabó el plazo,
  **502** en los demás casos; nunca 500 ([D20](../README.md#log-de-decisiones)).

### HU2 · Ver el clima de la ciudad elegida

Como usuario quiero ver el clima actual y el pronóstico por día de la ciudad que
elegí, para planear.

- `GET /v1/ciudades/{id}/clima?dias={1..16}` encadena dos llamadas distintas a
  Open-Meteo: `geocoding /v1/get?id=` y luego `forecast` con las coordenadas.
- Responde la ciudad resuelta, el clima actual (temperatura, humedad, código del
  tiempo, viento) y una lista **por día** (máxima, mínima, probabilidad de lluvia).
  Open-Meteo lo entrega en listas paralelas; nosotros lo juntamos por día.
- Las dos llamadas encadenadas comparten el plazo de 15 s de la petición
  ([D18](../README.md#log-de-decisiones)); si falla Open-Meteo, lo mismo que en HU1.
- `id` inexistente: Open-Meteo responde **400 «Location ID not found»** → nosotros
  respondemos **404** y no se reintenta.
- `dias` fuera de 1–16 → **422** antes de llamar a Open-Meteo.
- Respuestas de Open-Meteo que no cumplan el modelo Pydantic → error claro (502), no
  datos a medias.
- Usa caché con TTL ([P02](../README.md#decisiones-pendientes)).

### HU3 · Ver los sensores del campus aunque el servicio falle

Como usuario quiero la lista completa de sensores con su lectura actual, para ver
estadísticas por tipo y ubicación y compararlas con el clima exterior.

- `GET /v1/sensores` recorre **todas** las páginas del servicio inestable siguiendo
  el cursor `siguiente` hasta `null`.
- Pide la lectura de cada sensor con un máximo de 4 llamadas a la vez y una compuerta
  compartida de Retry-After ([D14](../README.md#log-de-decisiones)).
- Reintenta solo 503, 429, timeouts y errores de conexión, con backoff exponencial y
  jitter; respeta Retry-After; nunca reintenta 400 ni 404
  ([D12, D22](../README.md#log-de-decisiones)).
- Hasta 6 intentos por llamada, con timeouts de 3, 6 y 8 s, y nunca más de 45 s
  para toda la petición ([D17, D18, D19](../README.md#log-de-decisiones)).
- Si algo sigue fallando tras agotar los intentos o el plazo, devuelve lo que obtuvo
  con `completo: false` y el motivo ([D15](../README.md#log-de-decisiones)). Si no
  obtuvo ningún sensor, o ninguna lectura, responde **502/504**
  ([D20, D21](../README.md#log-de-decisiones)).
- La URL del servicio inestable se lee de una variable de entorno.

### HU4 · Crear una alerta sin duplicados

Como cliente que puede perder la respuesta y reintentar, quiero que repetir la misma
creación no genere dos alertas.

- Una alerta es un umbral registrado: objetivo (ciudad por id o sensor), variable,
  condición y umbral. Solo se guarda, no se evalúa
  ([D24](../README.md#log-de-decisiones)).
- `POST /v1/alertas` la crea: **201** con `Location`. `GET /v1/alertas` las lista y
  `GET /v1/alertas/{id}` trae una, o **404** si no existe.
- `Idempotency-Key` es obligatoria ([D25](../README.md#log-de-decisiones)):
  - sin clave → **400**;
  - misma clave y mismo cuerpo → **la misma** respuesta, sin crear otra alerta;
  - misma clave con otro cuerpo → **422**;
  - misma clave mientras la primera sigue en curso → **409**.
- Las alertas y las claves viven en memoria; las claves duran 24 h.

### HU5 · Saber si el agregador está vivo

- `GET /salud` propio, que no depende de las dependencias externas para responder.

### HU6 · Medir el efecto de la caché

- Latencia del endpoint de clima con caché y sin ella, registrada en una tabla del
  README ([P03, P04](../README.md#decisiones-pendientes)).

### HU8 · Levantar todo en contenedores con un comando

Como docente quiero levantar el agregador y el servicio inestable con un solo comando
en contenedores, y poder apuntar el agregador a mi propia instancia, para revisar la
entrega sin instalar dependencias en mi máquina ([D16](../README.md#log-de-decisiones)).

- `docker compose up --wait` levanta el agregador y el servicio inestable con una
  sola imagen ([D28, D29](../README.md#log-de-decisiones)).
- El servicio inestable arranca con `--host 0.0.0.0` (si no, no es alcanzable desde
  fuera de su contenedor) y sus parámetros de fallos se pasan por variables, sin
  editar archivos: `TASA_FALLOS=0.4 LATENCIA=5 docker compose up --wait`.
- `SERVICIO_INESTABLE_URL` apunta el agregador a otra instancia, incluida una que
  corre en otro contenedor de la máquina del docente, con `host.docker.internal`
  ([D30](../README.md#log-de-decisiones)).
- La colección de pruebas y la medición de latencia corren con
  `docker compose run --rm pruebas` ([D26, D28](../README.md#log-de-decisiones)).
- Los dos servicios tienen healthcheck a `/salud`; el agregador no espera al
  servicio inestable para arrancar, y las pruebas esperan a los dos
  ([D31](../README.md#log-de-decisiones)).
- `docker compose logs` muestra los intentos y las esperas desde el arranque (con
  `PYTHONUNBUFFERED=1`), porque esos logs son la evidencia de los reintentos.
- `docker stop` termina el agregador limpio, sin esperar los 10 s de gracia.

### HU7 · Dashboard (fase 2, después del backend)

- Página estática en `/dashboard` servida por el mismo FastAPI, con Chart.js, que
  solo habla con nuestra API ([D08](../README.md#log-de-decisiones)).
- Cuatro vistas ([D10](../README.md#log-de-decisiones)): panel de resiliencia,
  pronóstico de una ciudad (con el buscador de HU1), comparar ciudades, y sensores con
  la relación exterior vs interior.

## Definición de terminado (de la entrega)

1. Código del agregador y `requirements.txt`; URL del servicio inestable por variable
   de entorno.
2. README con integrantes y rol, API elegida, cómo arrancar servicio y agregador,
   tabla de latencias con y sin caché, demostración de idempotencia y respuestas a las
   preguntas a–d de la Parte D.
3. Evidencias de reintentos: registros donde se vean intentos, esperas y respeto de
   Retry-After.
4. Colección de peticiones de prueba que el docente pueda ejecutar, en pytest + httpx
   (D26).
5. `/docs` describe correctamente el contrato.
6. Dockerfile y Docker Compose con los que todo lo anterior corre en contenedores
   desde un clon limpio del repo (D16). No hay instrucciones sin Docker (D23).

## Cómo se califica (para priorizar)

| Criterio | Puntos | Historias |
|---|---|---|
| Consumo de la API externa: llamadas encadenadas, modelos, timeouts | 15 | HU1, HU2 |
| Diseño de la API propia: recursos, códigos de estado, OpenAPI | 20 | HU1–HU5 |
| Resiliencia: reintentos selectivos, backoff con jitter, Retry-After, paginación | 30 | HU3 |
| Caché con TTL y medición de latencia | 10 | HU2, HU6 |
| Idempotencia demostrada | 10 | HU4 |
| Preguntas de análisis | 15 | README |
| Consumo cruzado (opcional) | +10 | [P15](../README.md#decisiones-pendientes) |

La reproducibilidad y la desplegabilidad (HU8) no aparecen en esta tabla del
enunciado. El equipo las incluye porque, según el equipo, son temas importantes de la
evaluación. El docente confirmó que revisa con Docker
([D23](../README.md#log-de-decisiones)), así que el criterio de «ejecuta la colección
contra su propia instancia» depende directamente de HU8.
