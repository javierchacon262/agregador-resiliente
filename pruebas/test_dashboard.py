"""El dashboard se sirve desde el mismo FastAPI (D08)."""

from fastapi.testclient import TestClient

from agregador.main import app


def test_dashboard_se_sirve_como_html():
    with TestClient(app) as cliente:
        respuesta = cliente.get("/dashboard")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/html")
    assert "Agregador resiliente" in respuesta.text
