"""Un Open-Meteo falso para las pruebas sin red, con respuestas copiadas de las reales.

Responde según la ruta (`/v1/search`, `/v1/get`, `/v1/forecast`) y anota cada petición
que recibe, para comprobar cuántas llamadas se gastaron. Un guion por ruta permite
fallar los primeros intentos: cada paso es un código, un (código, json) o una excepción.
"""

import httpx

BUCARAMANGA = {
    "id": 3688465,
    "name": "Bucaramanga",
    "latitude": 7.125,
    "longitude": -73.11895,
    "country_code": "CO",
    "timezone": "America/Bogota",
    "population": 581130,
    "country": "Colombia",
    "admin1": "Santander",
}
SAN_JOSE_NARINO = {
    "id": 3669654,
    "name": "San José",
    "latitude": 1.69659,
    "longitude": -78.24482,
    "country_code": "CO",
    "population": 1772,
    "country": "Colombia",
    "admin1": "Nariño",
}
PRONOSTICO = {
    "timezone": "America/Bogota",
    "current": {
        "time": "2026-10-23T13:00",
        "interval": 900,
        "temperature_2m": 28.6,
        "relative_humidity_2m": 57,
        "weather_code": 3,
        "wind_speed_10m": 7.5,
    },
    "daily": {
        "time": ["2026-10-23", "2026-10-24", "2026-10-25"],
        "temperature_2m_max": [28.7, 26.7, 26.4],
        "temperature_2m_min": [21.0, 20.6, 20.3],
        "precipitation_probability_max": [84, 96, None],
    },
}
NO_ENCONTRADA = {"reason": "Location ID not found.", "error": True}


class OpenMeteoFalso:
    def __init__(self, **guiones) -> None:
        # guiones: search=[...], get=[...], forecast=[...]; sin guion, la respuesta buena.
        self.guiones = {ruta: list(pasos) for ruta, pasos in guiones.items()}
        self.peticiones: list[httpx.Request] = []

    def rutas(self) -> list[str]:
        return [peticion.url.path for peticion in self.peticiones]

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.peticiones.append(peticion)
        ruta = peticion.url.path.rsplit("/", 1)[-1]
        guion = self.guiones.get(ruta)
        if guion:
            paso = guion.pop(0)
            if isinstance(paso, Exception):
                raise paso
            if isinstance(paso, tuple):
                return httpx.Response(paso[0], json=paso[1])
            if paso != 200:
                return httpx.Response(paso, json={"error": True, "reason": "falso"})
        return httpx.Response(200, json=self._bueno(ruta, peticion))

    @staticmethod
    def _bueno(ruta: str, peticion: httpx.Request) -> dict:
        if ruta == "search":
            nombre = peticion.url.params["name"].lower()
            if "san jos" in nombre:
                return {"results": [SAN_JOSE_NARINO], "generationtime_ms": 0.5}
            if "bucaramanga" in nombre:
                return {"results": [BUCARAMANGA], "generationtime_ms": 0.5}
            return {"generationtime_ms": 0.1}  # sin coincidencias: sin `results` (E1)
        if ruta == "get":
            if peticion.url.params["id"] == str(BUCARAMANGA["id"]):
                return BUCARAMANGA
            raise AssertionError("usar un guion para los demás ids")
        return PRONOSTICO

    def cliente(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self), base_url=base_url)
