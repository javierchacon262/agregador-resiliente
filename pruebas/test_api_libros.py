"""Colección: GET /v1/libros contra el stack y la API real del otro grupo (Parte E, D44).

Su servidor corre en el computador de otro grupo, detrás de un túnel de Cloudflare, así
que puede no estar prendido cuando se corra la colección. Por eso, como con el servicio
inestable (D26), se afirman invariantes: 200 con la obra, o el 502/504 que corresponde
a una dependencia caída, nunca un 500.
"""

CAMPOS = {"obra", "autor", "clave_autor", "nombre_personal_real", "fecha_nacimiento"}


def test_buscar_un_libro_en_la_api_del_otro_grupo(api):
    """D44, D45: «Cien años de soledad» trae a García Márquez, con sus campos; o, si su
    servidor no está, 502/504 con el cuerpo de D20."""
    respuesta = api.get("/v1/libros", params={"titulo": "Cien años de soledad"})
    assert respuesta.status_code in (200, 502, 504)
    if respuesta.status_code == 200:
        libro = respuesta.json()
        assert set(libro) == CAMPOS
        assert "García Márquez" in libro["autor"]
    else:
        assert respuesta.json()["dependencia"] == "otro_grupo"


def test_titulo_vacio_da_422(api):
    """Se valida antes de llamarlos."""
    assert api.get("/v1/libros", params={"titulo": ""}).status_code == 422
