# Instrucciones para agentes y personas que continúan este proyecto

Agregador resiliente de APIs en FastAPI (Parcial 2 de Sistemas Distribuidos, UIS):
consume Open-Meteo y un servicio que falla a propósito, y expone una API propia
resiliente con un dashboard encima. El requerimiento se trabaja con **SPDD**.

## Dónde quedó el trabajo

El 2026-10-17 Javier, con su agente, hizo los pasos 1 y 3 de SPDD, e iteró con el
equipo 15 decisiones en tres rondas de preguntas. Después el equipo agregó D16:
Docker para todo lo que se ejecute. Ese trabajo se fusionó en `main` con el PR #1.

El 2026-10-23 se hizo la ronda 5, en la rama `docs/cierra-pendientes-resiliencia`.
Las decisiones D17–D22 cierran los pendientes de resiliencia (P08, P09, P11 y P12)
con el apoyo de una simulación, y se confirmaron D07 y los supuestos S1–S3. En la
ronda 6, sobre el mismo PR, el equipo agregó D23: nada fuera de Docker, tampoco con el
docente (él lo confirmó), lo que cierra P20 y R4.

El mismo día se hizo la ronda 7, en la rama `docs/idempotencia-y-docker`, creada
desde la de la ronda 5 porque su PR seguía abierto. D24–D25 definen la alerta y la
idempotencia; D26 elige pytest + httpx para la colección de pruebas (P22, un pendiente
que salió en la ronda); D27 descarta la CI (riesgo R5, aceptado), y D28–D31 definen
cómo se arma Docker, verificado con Compose (hallazgos C5–C7). **Sigue sin haber
código de la aplicación**: el equipo pidió cerrar las decisiones antes de desarrollar.

Leer en este orden:

1. [`README.md`](README.md): estado, log de decisiones D01–D31, riesgos R1–R5,
   pendientes que quedan y supuestos S1–S3.
2. [`requirements/AR-001-…-[Story]-…`](requirements/): historias HU1–HU8 con sus
   criterios de aceptación.
3. [`spdd/analysis/AR-001-…-[Analysis]-…`](spdd/analysis/): lo que se encontró
   explorando Open-Meteo y leyendo `servicio_inestable.py`. Las secciones 1–3 están
   verificadas con peticiones reales; la 4 es una simulación de los reintentos
   ([`simulacion_reintentos.py`](spdd/analysis/simulacion_reintentos.py)), que hay
   que validar con el servicio real cuando exista el código.
4. [`spdd/template/REASONS-canvas.md`](spdd/template/REASONS-canvas.md): la plantilla
   del siguiente paso.

## Reglas

1. **No escribir código de la aplicación** hasta que el canvas REASONS esté escrito y
   el equipo lo haya revisado. Es una decisión del equipo, no una sugerencia.
2. **Las decisiones se iteran con el equipo; el agente no decide solo.** Se presenta
   cada pregunta con sus opciones, se marca una recomendada y se explica qué cambia
   con cada una. Cuando el equipo confirma:
   - se agrega una fila a la tabla «Log de decisiones» del README con el siguiente ID
     (D32, D33, …), las alternativas descartadas, el porqué, la sección REASONS que
     alimenta y la ronda;
   - si cierra un pendiente, se borra de la tabla de pendientes y la decisión dice
     «cierra P0X»;
   - si modifica una decisión anterior, esa no se borra: se le agrega la nota
     «Ajustada por DXX» (como D13 y D19);
   - se actualiza el contador de la sección «Estado».
3. **Primero el canvas, después el código.** Si cambia el comportamiento, se corrige
   el canvas y luego se regenera el código. Si es un refactor sin cambio de
   comportamiento, se cambia el código y luego se sincroniza el canvas. Las secciones
   del canvas no se editan a mano sin dejar constancia de por qué.
4. La sección «D12 en detalle» del README explica los reintentos función por función.
   El equipo la pidió porque es lo que más pesa en la evaluación. Cuando exista el
   código, esa sección debe describir el código real, función por función, sin
   adelantarse ni quedarse atrás.
5. **No modificar `servicio_inestable.py`**: es del docente y se configura por
   parámetros de arranque.
6. Idioma: español en la API, el código, los commits y los documentos (supuesto S1).
7. Los diagramas Mermaid deben renderizar en GitHub. Hay que probarlos antes de hacer
   commit.
8. Git: una rama y un PR por cada cosa terminada, con Conventional Commits. Nunca se
   hace push directo a `main`. Prefijos de rama: `docs/`, `feat/`, `fix/`.
9. **Todo lo que se ejecute del prototipo corre en contenedores** (D16): el agregador,
   el servicio inestable, las pruebas y la medición de latencia. Las instrucciones de
   arranque son solo con Docker: no hay plan B con `venv`, tampoco con el docente (D23).
   El servicio inestable va siempre con `--host 0.0.0.0` dentro de un contenedor
   (hallazgo C1 del análisis).

## Próximos pasos, en orden

1. **Cerrar los pendientes que quedan con el equipo**, en rondas cortas de preguntas.
   Quedan nueve. Conviene seguir con P13 (formato del log de evidencias), porque esos
   logs son la prueba de los reintentos, que valen 30 puntos; con P02–P05 (caché,
   medición de latencia y métricas), que valen 10, y con P01 (integrantes y roles),
   que va en el README de la entrega.
2. Revisar el análisis en equipo y cambiar su estado a «revisado».
3. Escribir el canvas en
   `spdd/prompt/AR-001-AAAAMMDDhhmm-[Feat]-agregador-backend.md` a partir de la
   plantilla. Cada afirmación debe citar las D y P de las que depende.
4. Revisar el canvas en equipo.
5. Solo entonces generar código, tarea por tarea según la sección Operations: primero
   el backend (D09) y después el dashboard. Con el backend listo, medir
   `GET /v1/sensores` contra el servicio real y comparar con la simulación (sección 4
   del análisis); si no coincide, se corrige primero el canvas.

## Cómo seguir

El PR #1 (`docs/requerimientos-iniciales`) ya se fusionó en `main`. Cada ronda o
cosa terminada va en su propia rama, creada desde `main`, y en su propio PR (regla 8).
Si el PR anterior sigue abierto, la rama nueva se crea desde la suya y su PR apunta a
ella, para mostrar solo lo nuevo (así se hizo la ronda 7 sobre la 5 y 6); cuando el
anterior se fusiona, se cambia la base a `main`. Para que la colaboración se vea en el
repo, los demás integrantes pueden revisar y comentar el PR abierto, o sumarle commits
a su rama mientras no se fusione:

```bash
gh repo clone javierchacon262/agregador-resiliente
cd agregador-resiliente
git switch main && git pull
git switch -c docs/lo-que-sigue
# … trabajar, y luego:
git add -A && git commit -m "docs(decisiones): cierra P13"
git push -u origin docs/lo-que-sigue
gh pr create
```
