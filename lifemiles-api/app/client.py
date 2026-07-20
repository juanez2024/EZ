"""Cliente de búsqueda de premios LifeMiles.

IMPORTANTE
----------
LifeMiles NO publica una API oficial. Un cliente "live" reproduce la misma
request que hace su propio sitio web al buscar disponibilidad de premios.
El contrato exacto (URL, headers, forma del JSON) cambia con el tiempo y
NO está documentado públicamente, así que este módulo lo aísla en dos
puntos claramente marcados —``_build_request`` y ``_parse_response``— que
tenés que ajustar con la request real capturada desde las DevTools del
navegador (ver README -> "Capturar el endpoint real").

Mientras tanto, ``MockLifeMilesClient`` genera datos simulados para que todo
el pipeline (scheduler, detección de deals, alertas, API) sea verificable
sin credenciales ni tráfico real.
"""
from __future__ import annotations

import abc
import hashlib
import logging
from datetime import date

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .models import Offer

log = logging.getLogger("lifemiles.client")


class LifeMilesClient(abc.ABC):
    """Interfaz común: buscar disponibilidad para una ruta/fecha/cabina."""

    @abc.abstractmethod
    def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: str,
        passengers: int,
    ) -> list[Offer]:
        ...

    def close(self) -> None:  # pragma: no cover - opcional
        pass


class MockLifeMilesClient(LifeMilesClient):
    """Genera ofertas deterministas a partir de los parámetros de búsqueda.

    Útil para desarrollo/tests: mismo input => mismo output, sin red.
    """

    def search(self, origin, destination, depart_date, cabin, passengers):
        seed = int(
            hashlib.sha256(
                f"{origin}{destination}{depart_date}{cabin}".encode()
            ).hexdigest(),
            16,
        )
        base = 25000 if cabin == "economy" else 80000
        # Variación pseudo-aleatoria pero estable: +/- ~40%.
        spread = (seed % 800) / 1000.0  # 0.0 .. 0.8
        miles = int(base * (0.7 + spread))
        seats = 1 + (seed % 6)
        taxes = 45.0 if cabin == "economy" else 120.0
        return [
            Offer(
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                cabin=cabin,
                miles=miles,
                taxes=taxes,
                currency="USD",
                carrier="AV",
                seats_left=seats,
            )
        ]


class LiveLifeMilesClient(LifeMilesClient):
    """Cliente real contra el endpoint de disponibilidad configurado.

    Ajustá ``_build_request`` y ``_parse_response`` a la request real."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client = httpx.Client(
            base_url=settings.lifemiles_base_url,
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                # Un User-Agent de navegador real reduce bloqueos triviales.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                ),
            },
        )

    # -- PUNTO DE AJUSTE 1: cómo se arma la request --
    def _build_request(
        self, origin, destination, depart_date, cabin, passengers
    ) -> dict:
        """Construye el body JSON de la búsqueda.

        Reemplazá estas claves por las del payload real que capturaste.
        """
        payload = {
            "origin": origin,
            "destination": destination,
            "departureDate": depart_date.isoformat(),
            "cabinClass": cabin.upper(),
            "adults": passengers,
            "awardType": "REDEMPTION",
        }
        headers = {}
        if self._s.lifemiles_api_key:
            headers["Authorization"] = f"Bearer {self._s.lifemiles_api_key}"
        return {"json": payload, "headers": headers}

    # -- PUNTO DE AJUSTE 2: cómo se lee la respuesta --
    def _parse_response(
        self, data: dict, origin, destination, depart_date, cabin
    ) -> list[Offer]:
        """Traduce el JSON de respuesta a objetos ``Offer``.

        Ajustá las rutas de acceso (``data["itineraries"]`` etc.) a la
        forma real de la respuesta.
        """
        offers: list[Offer] = []
        for item in data.get("itineraries", []):
            try:
                offers.append(
                    Offer(
                        origin=origin,
                        destination=destination,
                        depart_date=depart_date,
                        cabin=cabin,
                        miles=int(item["miles"]),
                        taxes=float(item.get("taxes", 0.0)),
                        currency=item.get("currency", "USD"),
                        carrier=item.get("carrier", ""),
                        seats_left=item.get("seatsAvailable"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Ítem de respuesta ignorado (%s): %s", exc, item)
        return offers

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        reraise=True,
    )
    def _post(self, req: dict) -> httpx.Response:
        resp = self._client.post(self._s.lifemiles_search_path, **req)
        resp.raise_for_status()
        return resp

    def search(self, origin, destination, depart_date, cabin, passengers):
        req = self._build_request(origin, destination, depart_date, cabin, passengers)
        try:
            resp = self._post(req)
        except httpx.HTTPStatusError as exc:
            log.error(
                "Búsqueda %s-%s %s falló: HTTP %s",
                origin, destination, depart_date, exc.response.status_code,
            )
            return []
        except httpx.HTTPError as exc:
            log.error("Búsqueda %s-%s %s falló: %s", origin, destination, depart_date, exc)
            return []
        return self._parse_response(resp.json(), origin, destination, depart_date, cabin)

    def close(self) -> None:
        self._client.close()


def build_client(settings: Settings) -> LifeMilesClient:
    if settings.lifemiles_mode == "live":
        log.info("Cliente LifeMiles en modo LIVE (%s)", settings.lifemiles_base_url)
        return LiveLifeMilesClient(settings)
    log.info("Cliente LifeMiles en modo MOCK (sin red)")
    return MockLifeMilesClient()
