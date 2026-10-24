"""Lo común de la colección de pruebas contra el stack levantado (D26).

Las pruebas `test_api_*` usan el fixture `api`, un cliente httpx hacia el agregador
de `AGREGADOR_URL`. El Compose la pone al correr `docker compose run --rm pruebas`;
sin ella (p. ej. al correr solo las unitarias con `--no-deps -e AGREGADOR_URL=`),
esas pruebas se saltan.
"""

import os
import uuid

import httpx
import pytest


@pytest.fixture(scope="session")
def api():
    url = os.environ.get("AGREGADOR_URL")
    if not url:
        pytest.skip("AGREGADOR_URL no está definida: la colección necesita el stack levantado")
    # Más que el plazo más largo de una petición (45 s en sensores, D18).
    with httpx.Client(base_url=url, timeout=60) as cliente:
        yield cliente


@pytest.fixture
def clave():
    """Una Idempotency-Key nueva por prueba, como la generaría un cliente."""
    return f"prueba-{uuid.uuid4()}"
