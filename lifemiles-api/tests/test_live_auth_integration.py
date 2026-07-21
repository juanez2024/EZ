"""Integración: el cliente live inyecta el token del provider en la request.

Sin red real: se mockea el httpx.Client del cliente para capturar el header
Authorization y devolver la respuesta-fixture real.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from app.client import LiveLifeMilesClient
from app.config import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "air_redemption_bog_mad.json"


class _StubProvider:
    def __init__(self, token):
        self._t = token
        self.calls = 0

    def get_access_token(self, force=False):
        self.calls += 1
        return self._t

    def close(self):
        pass


def test_client_sends_provider_token_and_parses():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["realm"] = request.headers.get("realm")
        seen["path"] = request.url.path
        return httpx.Response(200, json=fixture)

    settings = Settings(lifemiles_mode="live")
    provider = _StubProvider("FRESH-TOKEN-123")
    client = LiveLifeMilesClient(settings, token_provider=provider)
    # Reemplazar el transport por el mock (sin red).
    client._client = httpx.Client(
        base_url=settings.lifemiles_base_url,
        transport=httpx.MockTransport(handler),
        headers={"realm": settings.lifemiles_realm},
    )

    offers = client.search("BOG", "MAD", date(2026, 8, 29), "economy", 1)

    assert seen["auth"] == "Bearer FRESH-TOKEN-123"
    assert seen["realm"] == "lifemiles"
    assert seen["path"] == "/svc/air-redemption-find-flight-private"
    assert provider.calls == 1
    assert offers and any(o.miles == 118000 for o in offers)


def test_client_without_provider_uses_manual_api_key():
    """Con api_key manual y sin refresh/credenciales, no crea provider."""
    settings = Settings(lifemiles_mode="live", lifemiles_api_key="MANUAL-TOKEN")
    client = LiveLifeMilesClient(settings)
    assert client._token_provider is None
    req = client._build_request("BOG", "MAD", date(2026, 8, 29), "economy", 1)
    assert req["headers"]["Authorization"] == "Bearer MANUAL-TOKEN"
