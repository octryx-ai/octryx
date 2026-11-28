"""Authentication of a custom REST call with the connection's technical account."""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

#: Write-only fields of a connection, per scheme; a value lives in the secret store, the row holds its ref.
SECRET_FIELDS = ("api_key", "token", "password", "client_secret")
REQUIRED_SECRETS = {
    "api_key_header": ("api_key",),
    "api_key_query": ("api_key",),
    "bearer": ("token",),
    "basic": ("password",),
    "oauth2_client_credentials": ("client_secret",),
}
REQUIRED_FIELDS = {"basic": ("username",), "oauth2_client_credentials": ("client_id",)}
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_EXPIRY_MARGIN_SECONDS = 30.0


class AuthConfigError(ValueError):
    pass


@dataclass
class AppliedAuth:
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)

    def secret_values(self) -> list[str]:
        return [value for value in (*self.headers.values(), *self.query.values()) if value]


def require_credentials(scheme: str, config: dict[str, Any]) -> None:
    for name in (*REQUIRED_FIELDS.get(scheme, ()), *REQUIRED_SECRETS.get(scheme, ())):
        if not str(config.get(name) or "").strip():
            raise AuthConfigError(
                f"The connection has no {name} for the API's '{scheme}' authentication. A platform admin can set it "
                "(Connections › REST APIs › connection)."
            )


def _cache_key(connection_id: str, token_url: str, client_id: str, secret: str, scope: str) -> str:
    digest = hashlib.sha256(f"{token_url}\n{client_id}\n{secret}\n{scope}".encode()).hexdigest()
    return f"{connection_id}:{digest}"


async def _client_credentials_token(
    client: httpx.AsyncClient, *, connection_id: str, auth: dict[str, Any], config: dict[str, Any]
) -> str:
    token_url = str(config.get("token_url") or auth.get("token_url") or "").strip()
    if not token_url:
        raise AuthConfigError("The API's OAuth2 client-credentials authentication names no token_url.")
    scope = str(config.get("scope") or " ".join(auth.get("scopes") or [])).strip()
    client_id, secret = str(config["client_id"]), str(config["client_secret"])
    key = _cache_key(connection_id, token_url, client_id, secret, scope)
    cached = _TOKEN_CACHE.get(key)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    form = {"grant_type": "client_credentials", **({"scope": scope} if scope else {})}
    audience = str(config.get("audience") or "").strip()
    if audience:
        form["audience"] = audience
    response = await client.post(token_url, data=form, auth=(client_id, secret), follow_redirects=False)
    if response.status_code >= 400:
        raise AuthConfigError(f"The token endpoint refused the client credentials (HTTP {response.status_code}).")
    try:
        payload = response.json()
        token = str(payload["access_token"])
    except (ValueError, KeyError, TypeError):
        raise AuthConfigError("The token endpoint answered without an access_token.") from None
    expires_in = float(payload.get("expires_in") or 300)
    _TOKEN_CACHE[key] = (token, time.monotonic() + max(0.0, expires_in - _EXPIRY_MARGIN_SECONDS))
    return token


async def apply_auth(
    client: httpx.AsyncClient, *, connection_id: str, auth: dict[str, Any], config: dict[str, Any]
) -> AppliedAuth:
    scheme = str(auth.get("scheme") or "none")
    if scheme == "none":
        return AppliedAuth()
    require_credentials(scheme, config)
    if scheme == "api_key_header":
        return AppliedAuth(headers={str(auth.get("header_name") or "X-API-Key"): str(config["api_key"])})
    if scheme == "api_key_query":
        return AppliedAuth(query={str(auth.get("query_name") or "api_key"): str(config["api_key"])})
    if scheme == "bearer":
        return AppliedAuth(headers={"Authorization": f"Bearer {config['token']}"})
    if scheme == "basic":
        raw = f"{config['username']}:{config['password']}".encode()
        return AppliedAuth(headers={"Authorization": f"Basic {base64.b64encode(raw).decode()}"})
    if scheme == "oauth2_client_credentials":
        token = await _client_credentials_token(client, connection_id=connection_id, auth=auth, config=config)
        return AppliedAuth(headers={"Authorization": f"Bearer {token}"})
    raise AuthConfigError(f"Unsupported authentication scheme: {scheme}")


def reserved_names(auth: dict[str, Any]) -> frozenset[str]:
    names = {"authorization"}
    if auth.get("scheme") == "api_key_header":
        names.add(str(auth.get("header_name") or "X-API-Key").lower())
    if auth.get("scheme") == "api_key_query":
        names.add(str(auth.get("query_name") or "api_key").lower())
    csrf = auth.get("csrf")
    if isinstance(csrf, dict) and csrf.get("fetch"):
        names.add(str(csrf.get("header") or "x-csrf-token").lower())  # the token comes from the fetch only
    return frozenset(names)


__all__ = [
    "REQUIRED_FIELDS",
    "REQUIRED_SECRETS",
    "SECRET_FIELDS",
    "AppliedAuth",
    "AuthConfigError",
    "apply_auth",
    "require_credentials",
    "reserved_names",
]
