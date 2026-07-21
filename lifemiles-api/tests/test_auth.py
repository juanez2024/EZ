"""Tests del TokenProvider con transports mockeados (sin red ni credenciales).

Se verifica la lógica de renovación, rotación de refresh token, caché en
disco, expiración/uso de cache en memoria y fallbacks — todo contra un
``httpx.MockTransport`` que simula al SSO de LifeMiles.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from app.auth import TokenError, TokenProvider

TOKEN_URL = "https://sso.example/auth/realms/lifemiles/protocol/openid-connect/token"


def _mock_sso(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _form(request: httpx.Request) -> dict:
    return dict(httpx.QueryParams(request.content.decode()))


def test_refresh_token_grant_returns_access_token():
    calls = []

    def handler(request):
        body = _form(request)
        calls.append(body)
        assert body["grant_type"] == "refresh_token"
        assert body["client_id"] == "lm-prd"
        assert body["refresh_token"] == "seed-refresh"
        return httpx.Response(200, json={
            "access_token": "ACCESS-1", "expires_in": 300,
            "refresh_token": "rotated-1",
        })

    tp = TokenProvider(
        TOKEN_URL, "lm-prd", refresh_token="seed-refresh",
        http_client=_mock_sso(handler),
    )
    assert tp.get_access_token() == "ACCESS-1"
    assert len(calls) == 1


def test_access_token_is_cached_until_expiry():
    def handler(request):
        return httpx.Response(200, json={
            "access_token": "ACCESS-CACHED", "expires_in": 300,
            "refresh_token": "r",
        })

    tp = TokenProvider(
        TOKEN_URL, "lm-prd", refresh_token="seed",
        http_client=_mock_sso(handler),
    )
    a = tp.get_access_token()
    b = tp.get_access_token()  # no debería re-pedir
    assert a == b == "ACCESS-CACHED"


def test_expired_token_triggers_new_request():
    seq = iter(["ACCESS-1", "ACCESS-2"])

    def handler(request):
        return httpx.Response(200, json={
            "access_token": next(seq),
            "expires_in": 10,  # con el margen de 45s, siempre se considera vencido
            "refresh_token": "r",
        })

    tp = TokenProvider(
        TOKEN_URL, "lm-prd", refresh_token="seed",
        http_client=_mock_sso(handler),
    )
    assert tp.get_access_token() == "ACCESS-1"
    assert tp.get_access_token() == "ACCESS-2"


def test_rotated_refresh_token_is_persisted_and_reused():
    tmp = Path(tempfile.mkdtemp()) / "tok.json"

    def handler(request):
        body = _form(request)
        # En la 2da corrida debe usar el refresh rotado, no el seed.
        return httpx.Response(200, json={
            "access_token": "A", "expires_in": 300,
            "refresh_token": "rotated-" + body["refresh_token"],
        })

    tp = TokenProvider(
        TOKEN_URL, "lm-prd", refresh_token="seed", cache_path=tmp,
        http_client=_mock_sso(handler),
    )
    tp.get_access_token()
    saved = json.loads(tmp.read_text())
    assert saved["refresh_token"] == "rotated-seed"

    # Un provider nuevo sin seed debe cargar el refresh rotado del cache.
    seen = {}

    def handler2(request):
        seen["refresh"] = _form(request)["refresh_token"]
        return httpx.Response(200, json={
            "access_token": "A2", "expires_in": 300, "refresh_token": "rotated2",
        })

    tp2 = TokenProvider(
        TOKEN_URL, "lm-prd", cache_path=tmp, http_client=_mock_sso(handler2),
    )
    assert tp2.get_access_token() == "A2"
    assert seen["refresh"] == "rotated-seed"


def test_refresh_failure_falls_back_to_password():
    def handler(request):
        body = _form(request)
        if body["grant_type"] == "refresh_token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        assert body["grant_type"] == "password"
        assert body["username"] == "user@x" and body["password"] == "pw"
        return httpx.Response(200, json={
            "access_token": "VIA-PASSWORD", "expires_in": 300,
        })

    tp = TokenProvider(
        TOKEN_URL, "lm-prd", refresh_token="bad",
        username="user@x", password="pw",
        http_client=_mock_sso(handler),
    )
    assert tp.get_access_token() == "VIA-PASSWORD"


def test_no_credentials_raises():
    tp = TokenProvider(TOKEN_URL, "lm-prd", http_client=_mock_sso(
        lambda r: httpx.Response(200, json={})
    ))
    with pytest.raises(TokenError):
        tp.get_access_token()


def test_sso_error_raises_tokenerror():
    def handler(request):
        return httpx.Response(503, text="upstream down")

    tp = TokenProvider(
        TOKEN_URL, "lm-prd", refresh_token="seed",
        http_client=_mock_sso(handler),
    )
    with pytest.raises(TokenError):
        tp.get_access_token()


def test_response_without_access_token_raises():
    def handler(request):
        return httpx.Response(200, json={"expires_in": 300})

    tp = TokenProvider(
        TOKEN_URL, "lm-prd", refresh_token="seed",
        http_client=_mock_sso(handler),
    )
    with pytest.raises(TokenError):
        tp.get_access_token()
