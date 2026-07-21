"""Verifica ``LiveLifeMilesClient._parse_response`` contra una respuesta REAL.

El fixture ``fixtures/air_redemption_bog_mad.json`` es la respuesta capturada
del endpoint real ``/svc/air-redemption-find-flight-private`` (búsqueda de
premios BOG->MAD, solo ida). Sin token ni red: solo ejercita el parser.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.client import LiveLifeMilesClient
from app.config import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "air_redemption_bog_mad.json"


def _client() -> LiveLifeMilesClient:
    return LiveLifeMilesClient(Settings())


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_economy_offers_from_real_response():
    client = _client()
    offers = client._parse_response(
        _load(), "BOG", "MAD", date(2026, 8, 29), "economy"
    )
    assert offers, "debería extraer al menos una oferta de economy"
    for o in offers:
        assert o.origin == "BOG" and o.destination == "MAD"
        assert o.cabin == "economy"
        assert o.miles > 0
        assert o.carrier == "AV"  # Avianca opera BOG-MAD
        assert o.currency == "USD"
    # El primer vuelo del sample tiene 118.000 millas regulares en economy.
    assert any(o.miles == 118000 for o in offers)


def test_parses_business_offers_from_real_response():
    client = _client()
    offers = client._parse_response(
        _load(), "BOG", "MAD", date(2026, 8, 29), "business"
    )
    assert offers
    assert all(o.cabin == "business" for o in offers)
    # cabinCode 2 (ejecutiva) = 179.240 millas regulares en el primer vuelo.
    assert any(o.miles == 179240 for o in offers)


def test_economy_and_business_have_different_miles():
    client = _client()
    eco = client._parse_response(_load(), "BOG", "MAD", date(2026, 8, 29), "economy")
    biz = client._parse_response(_load(), "BOG", "MAD", date(2026, 8, 29), "business")
    assert min(o.miles for o in eco) < min(o.miles for o in biz)


def test_taxes_are_extracted():
    client = _client()
    offers = client._parse_response(
        _load(), "BOG", "MAD", date(2026, 8, 29), "economy"
    )
    assert any(o.taxes > 0 for o in offers)


def test_unknown_cabin_code_yields_no_offers():
    """Si la cabina no está en la respuesta, no inventa ofertas (no falsos)."""
    client = _client()
    # 'first' (code 4) no aparece en este sample BOG-MAD de Avianca.
    offers = client._parse_response(
        _load(), "BOG", "MAD", date(2026, 8, 29), "first"
    )
    assert offers == []


def test_build_request_shape():
    client = _client()
    req = client._build_request("BOG", "MAD", date(2026, 8, 29), "economy", 1)
    body = req["json"]
    assert body["od"]["orig"] == "BOG"
    assert body["od"]["dest"] == "MAD"
    assert body["od"]["depDate"] == "2026-08-29"
    assert body["cabin"] == "1"  # economy
    assert body["itinerary"] == "OW"
    assert body["paxNumByType"]["ADT"] == 1
    assert body["odAp"] == [{"org": "BOG", "dest": "MAD", "cabin": 1}]
