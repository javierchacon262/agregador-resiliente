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
cómo se arma Docker, verificado con Compose (hallazgos C5–C7).

También ese día, la ronda 8 cerró los nueve pendientes que quedaban, en la rama
`docs/cierra-pendientes-finales`, apilada sobre la de la ronda 7. D32–D35 definen la
caché, la medición de latencia y las métricas; D36, la búsqueda vacía; D37, el formato
del log de evidencias; D38, seguir con las plantillas propias; D39, hacer la Parte E
antes del dashboard, y D40, los roles. **No quedan pendientes**, pero **sigue sin
haber código de la aplicación**: lo siguiente es el canvas.

Los PR #2, #3 y #4 se fusionaron, pero el #3 y el #4 quedaron fusionados contra sus
ramas base y no contra `main` (ver «Cómo seguir»). Las rondas 7 y 8 llegaron a `main`
con un PR aparte, desde la rama `docs/rondas-7-y-8-a-main`.

Después se escribió el canvas del backend, en la rama `docs/canvas-backend`. El equipo
pidió un canvas breve, que cite las decisiones en vez de repetirlas, para pasar al
código en cuanto se revise. Al escribirlo salió P23: qué pide exactamente la Parte E,
porque el enunciado no estaba en el repo. Después se agregó el enunciado en
`requirements/enunciado/` y D41 cerró P23.

Con el canvas revisado (PR #6) empezó el código. Javier hizo la base y los reintentos
(tareas 1–6, PR #8). Maria Fernanda hizo, en la rama `feat/ciudades-alertas-y-pruebas`,
el cliente de Open-Meteo, la caché, las rutas de ciudades, las alertas con
idempotencia, la colección de ciudades y alertas, la medición de latencia y las
secciones de entrega del README (tareas 10–15). Javier hizo los sensores, su colección y
la validación de la simulación (tareas 7–9, rama `feat/sensores`), con el turno de envío
(D42) que salió al probar contra el servicio real (C8). El día de la entrega el equipo
descartó la Parte E (D43). Al día siguiente apareció el grupo de Open Library con su
API publicada, y la ronda 12 la retomó (D44–D48). Maria Fernanda escribió su canvas y la
hizo en la rama `feat/parte-e-consumo-cruzado` (tareas 16–19). Para que ellos consuman la
nuestra, se publica con un túnel rápido de Cloudflare en Docker (D49); el comando está en
la sección «Parte E» del README. Abrir un túnel público lo corre la persona, no el agente.

Leer en este orden:

0. [`requirements/enunciado/`](requirements/enunciado/enunciado.md): el enunciado del
   docente, en PDF y transcrito. Es la fuente de todo lo demás.
1. [`README.md`](README.md): estado, integrantes y roles, log de decisiones D01–D41,
   riesgos R1–R5 y supuestos S1–S3. La tabla de pendientes está vacía.
2. [`requirements/AR-001-…-[Story]-…`](requirements/): historias HU1–HU8 con sus
   criterios de aceptación.
3. [`spdd/analysis/AR-001-…-[Analysis]-…`](spdd/analysis/): lo que se encontró
   explorando Open-Meteo y leyendo `servicio_inestable.py`. Las secciones 1–3 están
   verificadas con peticiones reales; la 4 es una simulación de los reintentos
   ([`simulacion_reintentos.py`](spdd/analysis/simulacion_reintentos.py)), validada
   contra el servicio real en la tarea 9: coincide.
4. [`spdd/prompt/AR-001-…-[Feat]-agregador-backend.md`](spdd/prompt/): el canvas del
   backend. Su sección Operations es la lista de tareas del código, con el rol de cada
   una (D40).
5. [`spdd/template/REASONS-canvas.md`](spdd/template/REASONS-canvas.md): la plantilla,
   para el canvas que falta (el dashboard).

## Reglas

1. **No escribir código de la aplicación** hasta que el canvas REASONS esté escrito y
   el equipo lo haya revisado. Es una decisión del equipo, no una sugerencia.
2. **Las decisiones se iteran con el equipo; el agente no decide solo.** Se presenta
   cada pregunta con sus opciones, se marca una recomendada y se explica qué cambia
   con cada una. Cuando el equipo confirma:
   - se agrega una fila a la tabla «Log de decisiones» del README con el siguiente ID
     (D44, D45, …), las alternativas descartadas, el porqué, la sección REASONS que
     alimenta y la ronda;
   - si cierra un pendiente, se borra de la tabla de pendientes y la decisión dice
     «cierra P0X»;
   - si modifica una decisión anterior, esa no se borra: se le agrega la nota
     «Ajustada por DXX» (como D13 y D19);
   - se actualiza el contador de la sección «Estado».

   Si al escribir el canvas o el código aparece una pregunta nueva, se agrega a la
   tabla de pendientes con el siguiente ID (P24, P25, …), y no se genera código para esa parte hasta
   cerrarla.
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

1. El backend está completo (tareas 1–15). Para la entrega: el comprimido de `main`
   para Moodle con la lista de chequeo de `entrega/`.
2. Después de la entrega, si se retoma: el canvas del dashboard (D08, D10) y luego su
   código. La Parte E está en su canvas (D44–D48); si el otro grupo reinicia su túnel,
   cambiar `OTRO_GRUPO_URL` (D48).
3. Pendiente menor: revisar el análisis y marcarlo como «revisado».

## Cómo seguir

El PR #1 (`docs/requerimientos-iniciales`) ya se fusionó en `main`. Cada ronda o
cosa terminada va en su propia rama, creada desde `main`, y en su propio PR (regla 8).
Si el PR anterior sigue abierto, la rama nueva se crea desde la suya y su PR apunta a
ella, para mostrar solo lo nuevo (así se hizo la ronda 7 sobre la 5 y 6); cuando el
anterior se fusiona, se cambia la base a `main`.

> **Antes de fusionar un PR apilado, comprobar que su base ya sea `main`** (botón
> «Edit» junto al título del PR). GitHub solo cambia la base por su cuenta si la rama
> base se borra al fusionar el PR anterior; si no, el PR se fusiona contra la rama
> vieja y sus cambios nunca llegan a `main`. Eso pasó con los PR #3 y #4. Para que no
> se repita, conviene activar «Automatically delete head branches» en la
> configuración del repo, o no apilar y esperar a que se fusione el PR anterior.

Para que la colaboración se vea en el repo, los demás integrantes pueden revisar y
comentar el PR abierto, o sumarle commits a su rama mientras no se fusione:

```bash
gh repo clone javierchacon262/agregador-resiliente
cd agregador-resiliente
git switch main && git pull
git switch -c docs/canvas-backend
# … trabajar, y luego:
git add -A && git commit -m "docs(spdd): canvas REASONS del backend"
git push -u origin docs/canvas-backend
gh pr create
```
