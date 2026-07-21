"""Obtención y renovación automática del token de LifeMiles (Keycloak).

El endpoint de premios es privado: exige ``Authorization: Bearer <JWT>``. Ese
JWT lo emite el SSO de LifeMiles (Keycloak, realm ``lifemiles``) y **vive solo
unos minutos**, así que un monitoreo desatendido necesita renovarlo solo en
cada ciclo.

Contrato del SSO (verificado desde la config OIDC pública del realm)::

    token_endpoint : https://sso.lifemiles.com/auth/realms/lifemiles/protocol/openid-connect/token
    client_id      : lm-prd            (cliente público del sitio, PKCE, sin secret)
    grants         : refresh_token, password (ambos habilitados en el realm)

Mecanismo (en orden de preferencia)
-----------------------------------
1. **refresh_token** — el camino durable y recomendado. Juan inicia sesión UNA
   vez en su navegador (nadie más toca su contraseña), copia el ``refresh_token``
   y lo pone en ``LIFEMILES_REFRESH_TOKEN``. A partir de ahí el provider pide
   access tokens nuevos con ``grant_type=refresh_token``. Keycloak **rota** el
   refresh token en cada uso, así que el provider persiste el nuevo en un
   archivo de caché (gitignoreado) para sobrevivir reinicios. Para que dure
   meses, ese refresh token conviene que sea ``offline_access`` (ver README).

2. **password** (ROPC) — fallback si hay ``LIFEMILES_USERNAME`` /
   ``LIFEMILES_PASSWORD``. Puede NO funcionar si las cuentas están federadas a
   un IdP externo (el sitio usa ``kc_idp_hint=Lifemiles``); por eso el
   refresh_token es el camino principal.

Este módulo NO inicia sesión con contraseña por su cuenta durante los tests:
toda la lógica se ejercita con transports mockeados.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("lifemiles.auth")

# Margen de seguridad: renovar el token si le quedan menos de estos segundos.
_EXPIRY_MARGIN_S = 45


class TokenError(RuntimeError):
    """No se pudo obtener un access token válido."""


class TokenProvider:
    """Entrega un access token válido, renovándolo cuando hace falta.

    Es seguro llamar ``get_access_token()`` en cada request: cachea el token en
    memoria y solo pega contra el SSO cuando está por vencer.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        *,
        refresh_token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        scope: str = "openid",
        cache_path: str | Path | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._username = username or None
        self._password = password or None
        self._scope = scope
        self._cache_path = Path(cache_path) if cache_path else None
        # httpx.Client inyectable para tests (MockTransport).
        self._http = http_client or httpx.Client(timeout=30.0)
        self._owns_http = http_client is None

        # Estado en memoria.
        self._access_token: str | None = None
        self._access_exp: float = 0.0
        # El refresh token de arranque puede venir por parámetro o del cache.
        self._refresh_token = refresh_token or self._load_cached_refresh()

    # -- API pública --------------------------------------------------------

    def get_access_token(self, *, force: bool = False) -> str:
        """Devuelve un access token válido (renovando si está por vencer)."""
        if not force and self._access_token and time.time() < self._access_exp:
            return self._access_token
        return self._refresh()

    def close(self) -> None:  # pragma: no cover - trivial
        if self._owns_http:
            self._http.close()

    # -- Interno ------------------------------------------------------------

    def _refresh(self) -> str:
        if self._refresh_token:
            try:
                return self._grant(
                    {
                        "grant_type": "refresh_token",
                        "client_id": self._client_id,
                        "refresh_token": self._refresh_token,
                        "scope": self._scope,
                    }
                )
            except TokenError as exc:
                log.warning("refresh_token falló (%s); intento password si hay", exc)
        if self._username and self._password:
            return self._grant(
                {
                    "grant_type": "password",
                    "client_id": self._client_id,
                    "username": self._username,
                    "password": self._password,
                    "scope": self._scope,
                }
            )
        raise TokenError(
            "Sin credenciales para obtener token: configurá "
            "LIFEMILES_REFRESH_TOKEN (recomendado) o "
            "LIFEMILES_USERNAME/PASSWORD."
        )

    def _grant(self, data: dict) -> str:
        try:
            resp = self._http.post(
                self._token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:  # red caída, timeout, etc.
            raise TokenError(f"error de red contra el SSO: {exc}") from exc
        if resp.status_code != 200:
            body = resp.text[:300]
            raise TokenError(
                f"SSO respondió HTTP {resp.status_code} para "
                f"grant={data.get('grant_type')}: {body}"
            )
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise TokenError(f"respuesta del SSO no es JSON: {exc}") from exc

        access = payload.get("access_token")
        if not access:
            raise TokenError(f"respuesta del SSO sin access_token: {payload}")

        # expires_in (segundos) - margen de seguridad.
        expires_in = int(payload.get("expires_in", 60))
        self._access_token = access
        self._access_exp = time.time() + max(expires_in - _EXPIRY_MARGIN_S, 0)

        # Keycloak rota el refresh token: guardamos el nuevo para la próxima.
        new_refresh = payload.get("refresh_token")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            self._persist_refresh(new_refresh)

        log.info(
            "Access token renovado vía %s (expira en %ss)",
            data.get("grant_type"), expires_in,
        )
        return access

    # -- Persistencia del refresh token rotado ------------------------------

    def _load_cached_refresh(self) -> str | None:
        if not self._cache_path or not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return data.get("refresh_token") or None
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("No se pudo leer cache de token (%s)", exc)
            return None

    def _persist_refresh(self, refresh_token: str) -> None:
        if not self._cache_path:
            return
        try:
            self._cache_path.write_text(
                json.dumps({"refresh_token": refresh_token}),
                encoding="utf-8",
            )
            # Permisos restrictivos: es una credencial.
            try:
                self._cache_path.chmod(0o600)
            except OSError:  # pragma: no cover - FS sin permisos POSIX
                pass
        except OSError as exc:
            log.warning("No se pudo persistir el refresh token (%s)", exc)


def build_token_provider(settings) -> TokenProvider | None:
    """Crea el ``TokenProvider`` desde settings, o ``None`` si no aplica.

    Devuelve ``None`` cuando hay un ``LIFEMILES_API_KEY`` manual (token pegado
    a mano para una corrida puntual) y no hay refresh token ni credenciales:
    en ese caso el cliente usa el token fijo tal cual.
    """
    has_refresh = bool(getattr(settings, "lifemiles_refresh_token", ""))
    has_userpass = bool(settings.lifemiles_username and settings.lifemiles_password)
    if not (has_refresh or has_userpass):
        return None

    cache_path = getattr(settings, "lifemiles_token_cache", "") or None
    return TokenProvider(
        token_url=settings.lifemiles_token_url,
        client_id=settings.lifemiles_client_id,
        refresh_token=getattr(settings, "lifemiles_refresh_token", "") or None,
        username=settings.lifemiles_username or None,
        password=settings.lifemiles_password or None,
        scope=settings.lifemiles_scope,
        cache_path=cache_path,
    )
