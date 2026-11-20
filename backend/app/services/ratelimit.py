"""Rate limit por ventana deslizante, en memoria del proceso.

Alcanza para un backend de una sola instancia (el plan de v0.0.2). Con varias
instancias o workers cada una cuenta por su lado: el límite efectivo se multiplica.
Si el deploy escala, se mueve el contador a Postgres/Redis o se delega en el
proxy (Cloudflare); la interfaz (`intentar`) no cambia. Ver docs/04, §6.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import get_settings

_PURGA_CADA = 1000  # llamadas entre purgas de claves vencidas


class LimitadorVentana:
    def __init__(self) -> None:
        self._eventos: dict[str, deque[float]] = defaultdict(deque)
        self._llamadas = 0

    def reiniciar(self) -> None:
        self._eventos.clear()

    def intentar(
        self, clave: str, limite: int, ventana_s: float, ahora: float | None = None
    ) -> float | None:
        """Registra un intento. Devuelve None si entra, o los segundos a esperar si
        la clave ya agotó `limite` intentos en la última `ventana_s`."""
        ahora = time.monotonic() if ahora is None else ahora
        self._llamadas += 1
        if self._llamadas % _PURGA_CADA == 0:
            self._purgar(ahora, ventana_s)
        cola = self._eventos[clave]
        while cola and cola[0] <= ahora - ventana_s:
            cola.popleft()
        if len(cola) >= limite:
            return max(1.0, cola[0] + ventana_s - ahora)
        cola.append(ahora)
        return None

    def _purgar(self, ahora: float, ventana_s: float) -> None:
        for clave in [k for k, c in self._eventos.items() if not c or c[-1] <= ahora - ventana_s]:
            del self._eventos[clave]


limitador = LimitadorVentana()


def ip_cliente(request: Request) -> str:
    """IP del cliente. Detrás de proxies confiables (`PROXY_HOPS` > 0) se toma de
    `X-Forwarded-For` contando desde la derecha: lo que agrega nuestro propio proxy,
    no lo que el cliente escribe a la izquierda (eso se falsifica)."""
    hops = get_settings().proxy_hops
    if hops > 0:
        partes = [
            p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()
        ]
        if len(partes) >= hops:
            return partes[-hops]
    return request.client.host if request.client else "desconocida"


def limitar(clave: str, limite: int, ventana_s: float, mensaje: str) -> None:
    """429 con `Retry-After` si se agotó el límite."""
    espera = limitador.intentar(clave, limite, ventana_s)
    if espera is not None:
        raise HTTPException(
            429,
            detail={"codigo": "demasiados_intentos", "mensaje": mensaje},
            headers={"Retry-After": str(int(espera))},
        )
