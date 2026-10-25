# AR-001 · Canvas REASONS: Parte E, consumo cruzado

| Campo | Valor |
|---|---|
| ID | AR-001 |
| Historia | [AR-001 Story](../../requirements/AR-001-202610171311-[Story]-agregador-resiliente.md) |
| Enunciado | [Parte E](../../requirements/enunciado/enunciado.md#parte-e--consumo-cruzado-opcional-bonificación) |
| Contrato del otro grupo | [`requirements/parte-e/openapi-grupo-open-library.json`](../../requirements/parte-e/openapi-grupo-open-library.json), copiado el 2026-10-24 y comparado con el que publica su servidor: son iguales |
| Decisiones | D44–D48 del [log del README](../../README.md#log-de-decisiones) |
| Estado | revisado por Maria Fernanda; Javier lo revisa en el PR |
| Revisado por | Maria Fernanda (2026-10-24) |
| Fecha | 2026-10-24 |

Este canvas sigue las normas del [canvas del backend](AR-001-202610231215-[Feat]-agregador-backend.md)
y solo dice lo nuevo. Si el código y el canvas no coinciden, se corrige primero el
canvas (D02).

## R · Requirements (requisitos)

El enunciado pide consumir un endpoint de otro grupo **usando únicamente su
documentación OpenAPI**, y reportar en el README qué le faltó o le sobró al contrato
(D41). Consumimos el agregador del grupo de Open Library (D44), que expone
`GET /v1/libros?titulo=` y encadena por dentro la búsqueda de la obra con su autor.

| Ruta | Éxito | Errores | Decisiones |
|---|---|---|---|
| `GET /v1/libros?titulo=` | 200 con la obra y su autor; `Cache-Status` | 422 si `titulo` está vacío (su misma regla, `minLength: 1`) o pasa de 200 caracteres, sin llamar al otro grupo; 404 si su API responde 404; 502 si responde otro error o algo que no cumple su contrato; 504 si no responde a tiempo o se acaba el plazo | D45–D47, D20 |

**Terminado** cuando la ruta responde así contra su servidor real, las pruebas
unitarias cubren cada fila de la tabla sin red, la colección pasa con
`docker compose run --rm pruebas`, y el README tiene la sección de la Parte E con lo
que le faltó o le sobró a su contrato.

## E · Entities (entidades)

Modelo propio (`agregador/modelos.py`):

| Modelo | Campos |
|---|---|
| `Libro` | Los cinco campos de su `ResumenObra`, **con sus mismos nombres**: `obra`, `autor`, `clave_autor` (la clave de Open Library, p. ej. `OL27363A`), `nombre_personal_real` y `fecha_nacimiento` (los dos últimos pueden faltar) |

Modelo externo, para validar lo que llega (`clientes/otro_grupo.py`): `ResumenObra`
de su contrato, con `obra`, `autor` y `clave_autor` obligatorios, y
`nombre_personal_real` y `fecha_nacimiento` opcionales. `fecha_nacimiento` se deja como
texto, porque su contrato dice `string` sin formato.

Respondemos con sus nombres de campo y no con unos nuestros, para que quien lea su
contrato reconozca la respuesta y se vea que no agregamos nada que no esté en él.

## A · Approach (enfoque)

1. **El otro grupo es una dependencia más**, con la misma función de reintentos de
   D12: `llamar_con_reintentos` con una `Politica` propia de 2 intentos de hasta 10 s
   cada uno y plazo de 25 s por petición, sin compuerta (D50, que ajusta D46).
2. **Lo que responden, según su contrato:** 200 → validar y convertir; 404 («No se
   encontró una obra con autor») → 404 nuestro, sin reintentar; 503 y 429 → se
   reintentan; otro código → 502 sin reintentar (D20). Su 502 o su 504 son 502 para
   nosotros: significan que a ellos les falló Open Library, pero sí nos respondieron;
   nuestro 504 queda para cuando ellos no responden a tiempo, como en el resto de la API; timeout o plazo → 504; un cuerpo
   que no cumple `ResumenObra` (por ejemplo, la página HTML de error de Cloudflare)
   → 502 `respuesta_invalida`.
3. **Caché de 10 min** con `CacheTTL` y `Cache-Status: agregador-libros; …` (D51, que ajusta D47). La
   clave es el título sin mayúsculas ni espacios de los extremos. Un 404 o un error no
   se guardan.
4. **La URL viene de `OTRO_GRUPO_URL`** (D48). Si su túnel se cae, solo falla esta
   ruta: las demás no dependen de él.

## S · Structure (estructura)

```text
agregador/
  config.py              + OTRO_GRUPO_URL, MAXIMO_INTENTOS_OTRO_GRUPO, PLAZO_OTRO_GRUPO_S,
                           TIMEOUTS_LECTURA_OTRO_GRUPO_S, TTL_LIBROS_S
  main.py                + cliente, política y caché del otro grupo en el lifespan; router
  modelos.py             + Libro; «otro_grupo» en CuerpoErrorDependencia y Metricas
  metricas.py            + «otro_grupo» en DEPENDENCIAS
  clientes/otro_grupo.py buscar_libro y el modelo externo ResumenObra
  rutas/libros.py        GET /v1/libros
pruebas/
  test_otro_grupo.py     unitarias del cliente y la ruta, con un servidor falso
  test_api_libros.py     colección contra el stack y el servidor real del otro grupo
requirements/parte-e/    su openapi.json, tal como lo recibimos
docker-compose.yml       + OTRO_GRUPO_URL hacia el agregador
```

## O · Operations (operaciones)

| # | Tarea | Archivos | Cómo se comprueba | Rol |
|---|---|---|---|---|
| 16 | Configuración, modelos y cliente del otro grupo (D46, D48) | `config.py`, `modelos.py`, `metricas.py`, `clientes/otro_grupo.py`, `docker-compose.yml` | Unitarias con `MockTransport`: 200 convertido; 404 sin reintento; 503 reintentado; timeouts → 504; HTML → 502 | Maria Fernanda |
| 17 | Ruta y caché (D45, D47) | `rutas/libros.py`, `main.py` | 422 sin llamar; `Cache-Status` miss → hit; `/docs` documenta 404/502/504 | Maria Fernanda |
| 18 | Colección (D26) | `pruebas/test_api_libros.py` | Contra su servidor real: 200 con «Cien años de soledad», o 502/504 si su túnel está caído (invariantes, como con el servicio inestable) | Maria Fernanda |
| 19 | Reporte en el README (D41) | `README.md` | Sección «Parte E» con lo que le faltó o le sobró a su contrato, y cómo apuntar a otra URL | Maria Fernanda |

## N · Norms (normas)

Las del canvas del backend. Además:

| Variable | Por defecto | Decisión |
|---|---|---|
| `OTRO_GRUPO_URL` | `https://validation-seed-grill-junior.trycloudflare.com` | D48 |
| `MAXIMO_INTENTOS_OTRO_GRUPO` · `PLAZO_OTRO_GRUPO_S` | `2` · `25` | D50 |
| `TIMEOUTS_LECTURA_OTRO_GRUPO_S` | `10` | D50 |
| `TTL_LIBROS_S` | `600` | D51 |

En el log de evidencias, la etiqueta de la dependencia es `otro-grupo`; en métricas y
errores, `otro_grupo`.

## S · Safeguards (salvaguardas)

1. Solo se usa lo que dice su `openapi.json`. Lo que haga falta saber y no esté ahí,
   va al reporte como algo que le faltó al contrato, no se pregunta.
2. Nunca reintentar su 404 ni sus 4xx (D12).
3. Validar `titulo` (422) antes de llamar a su API.
4. Toda llamada lleva timeout, y ninguna petición pasa de 25 s (D50).
5. Un fallo suyo nunca sale como 500: 404, 502 o 504.
6. Si su servidor no está, el resto de nuestra API sigue igual.

## Cambios

Lo que se cambió en este canvas después de revisarlo, y por qué (regla 3 de AGENTS.md).

| Fecha | Tareas | Cambio | Por qué |
|---|---|---|---|
| 2026-10-25 | 16–18 | Reintentos hacia el otro grupo: de 3 intentos con 4 → 6 → 8 s y plazo de 20 s a **2 intentos de 10 s y plazo de 25 s** (D50). Caché de libros: de 24 h a **10 min** (D51) | Decisión de Maria Fernanda antes de fusionar: menos peticiones a una API que corre en el computador de otro grupo, cada una con tiempo de sobra para responder, y datos guardados por menos tiempo de un servicio que no controlamos. Cambia el comportamiento, así que se corrigió primero el canvas y después el código |
