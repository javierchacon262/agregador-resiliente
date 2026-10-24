# Entrega en Moodle

Una sola entrega por grupo, en un archivo comprimido (sección 6 del
[enunciado](../requirements/enunciado/enunciado.md)).

## Armar el comprimido

Desde `main`, con todo fusionado:

```bash
git switch main && git pull
git archive --format=zip --prefix=agregador-resiliente/ -o entrega/agregador-resiliente.zip main
```

`git archive` toma solo lo que está en git, así que el comprimido no lleva cachés,
entornos ni archivos sueltos. El `.zip` no se sube al repo (está en `.gitignore`).

## Lista de chequeo

Antes de subirlo, desde un clon limpio (R5: no hay CI que lo compruebe):

- [ ] `docker compose up -d --wait` deja sanos el agregador y el servicio inestable.
- [ ] `docker compose run --rm pruebas` termina en verde.
- [ ] `TASA_FALLOS=0.4 LATENCIA=5 docker compose up -d --wait` y otra vez
      `docker compose run --rm pruebas`: en verde con los parámetros del enunciado.

| Entregable (sección 6 del enunciado) | Dónde está |
|---|---|
| Código fuente del agregador y `requirements.txt` | `agregador/`, `requirements.txt` |
| URL del servicio inestable por variable de entorno | `SERVICIO_INESTABLE_URL` (README, «Cómo arrancar») |
| README: integrantes y rol | README, «Integrantes y roles» |
| README: API elegida | README: Open-Meteo (D01) |
| README: cómo arrancar el servicio inestable y el agregador | README, «Cómo arrancar el servicio inestable y el agregador» |
| README: tabla de latencias con caché y sin ella | README, «Latencia con caché y sin ella» |
| README: demostración de idempotencia | README, «Demostración de idempotencia» |
| README: respuestas a las preguntas de la Parte D | README, «Preguntas de análisis (Parte D)» |
| Evidencias de los reintentos | `evidencias/` y README, «Evidencias de los reintentos» |
| Colección de peticiones de prueba | `pruebas/` (`docker compose run --rm pruebas`) |
