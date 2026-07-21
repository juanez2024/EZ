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

from .auth import TokenError, build_token_provider
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

    # Aerolínea Star Alliance que suele operar cada destino (para simular
    # disponibilidad de socios, no solo Avianca).
    _CARRIER_BY_DEST = {
        "FRA": "LH", "ZRH": "LX", "IST": "TK", "NRT": "NH",
        "JFK": "UA", "GRU": "AV", "MAD": "AV", "MIA": "AV",
        "SCL": "AV",
    }
    _BASE_MILES = {"economy": 25000, "premium": 45000, "business": 80000}

    def search(self, origin, destination, depart_date, cabin, passengers):
        seed = int(
            hashlib.sha256(
                f"{origin}{destination}{depart_date}{cabin}".encode()
            ).hexdigest(),
            16,
        )
        base = self._BASE_MILES.get(cabin, 40000)
        # Variación pseudo-aleatoria pero estable: +/- ~40%.
        spread = (seed % 800) / 1000.0  # 0.0 .. 0.8
        miles = int(base * (0.7 + spread))
        seats = 1 + (seed % 6)
        taxes = {"economy": 45.0, "premium": 90.0}.get(cabin, 120.0)
        carrier = self._CARRIER_BY_DEST.get(destination, "AV")
        return [
            Offer(
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                cabin=cabin,
                miles=miles,
                taxes=taxes,
                currency="USD",
                carrier=carrier,
                seats_left=seats,
            )
        ]


class LiveLifeMilesClient(LifeMilesClient):
    """Cliente real contra el endpoint de disponibilidad de LifeMiles.

    Reproduce la request que hace el sitio web al buscar premios (redención
    de millas). El contrato fue capturado desde el buscador real
    (``/svc/air-redemption-find-flight-private``). ``_build_request`` y
    ``_parse_response`` están cableados a esa forma; ver
    ``capture/samples/`` para un ejemplo completo de request+response.

    AUTENTICACIÓN (importante)
    --------------------------
    El endpoint es privado: exige ``Authorization: Bearer <JWT>``. Ese token
    lo emite el SSO de LifeMiles (Keycloak) al iniciar sesión y **vive solo
    unos minutos**. Este cliente lo toma de ``settings.lifemiles_api_key``,
    así que para un monitoreo autónomo real hace falta un paso previo de
    login/refresh de token (aún no implementado). Con un token pegado a mano
    en ``.env`` sirve para una corrida puntual mientras el token siga vivo.
    """

    # Mapeo de cabina interno -> ``cabinCode`` de LifeMiles.
    # Confirmados desde la captura real: economy=1, business=2.
    # premium/first son la convención esperada pero NO verificados con una
    # captura (Avianca no vende premium economy en la ruta capturada); si un
    # socio Star Alliance no aparece, revisá el código con una nueva captura.
    _CABIN_CODE = {"economy": "1", "premium": "3", "business": "2", "first": "4"}

    def __init__(self, settings: Settings, token_provider=None) -> None:
        self._s = settings
        # Renovación automática de token (Keycloak). Si no hay refresh token ni
        # credenciales, queda None y se usa el api_key manual de settings.
        self._token_provider = token_provider or build_token_provider(settings)
        self._client = httpx.Client(
            base_url=settings.lifemiles_base_url,
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "realm": settings.lifemiles_realm,
                # Un User-Agent de navegador real reduce bloqueos triviales.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                ),
            },
        )

    def _bearer(self) -> str:
        """Token a usar: el auto-renovado si hay provider, si no el manual."""
        if self._token_provider is not None:
            return self._token_provider.get_access_token()
        return self._s.lifemiles_api_key

    # -- PUNTO DE AJUSTE 1: cómo se arma la request --
    def _build_request(
        self, origin, destination, depart_date, cabin, passengers
    ) -> dict:
        """Construye el body JSON de la búsqueda de premios.

        La forma sigue el payload real de
        ``/svc/air-redemption-find-flight-private``. Los campos derivados de
        la sesión web (``idCoti``, ``sch`` y los códigos de descuento de la
        cuenta) son opcionales: se incluyen solo si están configurados. El
        servidor puede exigir algunos de ellos; eso solo se confirma con un
        round-trip real (ver nota de AUTENTICACIÓN en la clase).
        """
        code = self._CABIN_CODE.get(cabin, "1")
        payload = {
            "internationalization": {
                "language": self._s.lifemiles_language,
                "country": self._s.lifemiles_country,
                "currency": self._s.lifemiles_currency.lower(),
            },
            "currencies": [{"currency": "USD", "decimal": 2, "rateUsd": 1}],
            "passengers": passengers,
            "od": {
                "orig": origin,
                "dest": destination,
                "departingCity": "",
                "arrivalCity": "",
                "depDate": depart_date.isoformat(),
                "depTime": "",
            },
            "filter": False,
            "codPromo": None,
            "officeId": "",
            "ftNum": "",
            "context": "D",
            "channel": "COM",
            "cabin": code,
            "itinerary": "OW",
            "odNum": 1,
            "usdTaxValue": "0",
            "getQuickSummary": False,
            "ods": "",
            "searchType": "SMR",
            "searchTypePrioritized": "AVH",
            "posCountry": self._s.lifemiles_country.upper(),
            "odAp": [{"org": origin, "dest": destination, "cabin": int(code)}],
            "suscriptionPaymentStatus": "",
            "paxNumByType": {"INF": 0, "CHD": 0, "YTH": 0, "ADT": passengers},
        }
        # Campos de sesión, opcionales (ver docstring).
        if self._s.lifemiles_id_coti:
            payload["idCoti"] = self._s.lifemiles_id_coti
        headers = {}
        token = self._bearer()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return {"json": payload, "headers": headers}

    @staticmethod
    def _carrier_of(trip: dict) -> str:
        """Código IATA de la aerolínea operadora del primer segmento.

        Se toma de ``flightsDetail`` (``operatedCompany``/``marketingCompany``),
        que trae el código limpio (ej. "AV", "LH"); es más confiable que el
        texto libre de ``operators`` ("Operado por ...").
        """
        for seg in trip.get("flightsDetail") or []:
            code = seg.get("operatedCompany") or seg.get("marketingCompany")
            if code:
                return code
        return ""

    @staticmethod
    def _seats_of(trip: dict, cabin_code: str) -> int | None:
        """Menor cantidad de sillas restantes para la cabina pedida."""
        seats: list[int] = []
        for product in trip.get("products") or []:
            if str(product.get("cabinCode")) != cabin_code:
                continue
            for flight in product.get("flights") or []:
                n = flight.get("remainingSeats")
                if isinstance(n, int) and n > 0:
                    seats.append(n)
        return min(seats) if seats else None

    # -- PUNTO DE AJUSTE 2: cómo se lee la respuesta --
    def _parse_response(
        self, data: dict, origin, destination, depart_date, cabin
    ) -> list[Offer]:
        """Traduce el JSON de respuesta a objetos ``Offer``.

        Una sola búsqueda devuelve todas las cabinas; acá filtramos a la
        cabina pedida leyendo ``lowestPriceByCabin`` de cada vuelo. Se usan
        las **millas regulares** (no el precio con descuentos de banco de la
        cuenta) para que el histórico sea comparable en el tiempo.
        """
        if data.get("status") not in (None, "success"):
            log.warning(
                "Respuesta con status inesperado (%s) para %s-%s %s",
                data.get("status"), origin, destination, depart_date,
            )
        code = self._CABIN_CODE.get(cabin, "1")
        offers: list[Offer] = []
        for trip in data.get("tripsList", []):
            price = next(
                (
                    p for p in trip.get("lowestPriceByCabin") or []
                    if str(p.get("cabinCode")) == code
                ),
                None,
            )
            if not price:
                continue
            try:
                miles = int(price["miles"])
            except (KeyError, TypeError, ValueError):
                continue
            if miles <= 0:  # cabina agotada para ese vuelo
                continue
            try:
                trip_date = date.fromisoformat(
                    trip.get("departingDate") or depart_date.isoformat()
                )
            except ValueError:
                trip_date = depart_date
            try:
                taxes = float(price.get("usdTaxValue") or 0.0)
            except (TypeError, ValueError):
                taxes = 0.0
            offers.append(
                Offer(
                    origin=trip.get("departingCityCode") or origin,
                    destination=trip.get("arrivalCityCode") or destination,
                    depart_date=trip_date,
                    cabin=cabin,
                    miles=miles,
                    taxes=taxes,
                    currency="USD",
                    carrier=self._carrier_of(trip),
                    seats_left=self._seats_of(trip, code),
                )
            )
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
        try:
            req = self._build_request(
                origin, destination, depart_date, cabin, passengers
            )
        except TokenError as exc:
            # Sin token no se puede buscar: se registra y se sigue con el ciclo.
            log.error("No hay token para %s-%s %s: %s", origin, destination, depart_date, exc)
            return []
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
        if self._token_provider is not None:
            self._token_provider.close()


def build_client(settings: Settings) -> LifeMilesClient:
    if settings.lifemiles_mode == "live":
        log.info("Cliente LifeMiles en modo LIVE (%s)", settings.lifemiles_base_url)
        return LiveLifeMilesClient(settings)
    log.info("Cliente LifeMiles en modo MOCK (sin red)")
    return MockLifeMilesClient()
