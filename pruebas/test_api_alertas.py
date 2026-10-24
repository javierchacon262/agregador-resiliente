"""Colección: alertas e idempotencia, contra el stack (HU4; D24, D25).

Es la demostración de la Parte D.2 del enunciado: dos peticiones repetidas con la misma
`Idempotency-Key` crean una sola alerta y devuelven la misma respuesta. Cada prueba usa
una clave nueva, así se puede correr la colección varias veces sin reiniciar.
"""

ALERTA = {"objetivo": {"tipo": "sensor", "id": "S-001"}, "variable": "co2", "condicion": "mayor_que", "umbral": 1000}


def test_dos_peticiones_con_la_misma_clave_crean_una_sola_alerta(api, clave):
    """Parte D.1 y D.2: misma clave y mismo cuerpo → 201 las dos veces, el mismo id y la
    misma respuesta; la lista tiene una alerta más, no dos."""
    antes = len(api.get("/v1/alertas").json())
    primera = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": clave})
    segunda = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": clave})
    assert primera.status_code == segunda.status_code == 201
    assert primera.json() == segunda.json()
    assert primera.headers["Location"] == segunda.headers["Location"] == f"/v1/alertas/{primera.json()['id']}"
    assert len(api.get("/v1/alertas").json()) == antes + 1


def test_la_alerta_creada_se_puede_leer(api, clave):
    """D24: Location apunta a la alerta, y GET la trae igual."""
    creada = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": clave})
    leida = api.get(creada.headers["Location"])
    assert (leida.status_code, leida.json()) == (200, creada.json())


def test_sin_idempotency_key_da_400(api):
    """D25: la clave es obligatoria."""
    respuesta = api.post("/v1/alertas", json=ALERTA)
    assert respuesta.status_code == 400


def test_misma_clave_con_otro_cuerpo_da_422(api, clave):
    """D25: reutilizar una clave para otra alerta es un error del cliente."""
    api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": clave})
    respuesta = api.post("/v1/alertas", json=ALERTA | {"umbral": 800}, headers={"Idempotency-Key": clave})
    assert respuesta.status_code == 422


def test_claves_distintas_crean_alertas_distintas(api, clave):
    """Una segunda alerta igual, hecha a propósito, lleva otra clave y se crea."""
    primera = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": clave})
    segunda = api.post("/v1/alertas", json=ALERTA, headers={"Idempotency-Key": f"{clave}-otra"})
    assert primera.json()["id"] != segunda.json()["id"]


def test_cuerpo_invalido_da_422(api, clave):
    respuesta = api.post("/v1/alertas", json=ALERTA | {"variable": "presion"}, headers={"Idempotency-Key": clave})
    assert respuesta.status_code == 422


def test_alerta_inexistente_da_404(api):
    assert api.get("/v1/alertas/a-9999").status_code == 404

