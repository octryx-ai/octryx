"""OAuth client registration and validation (RFC 7591 subset)."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlsplit

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...bcrypt_cost import bcrypt_salt
from ...models.security.oauth_provider import (
    ALLOWED_GRANT_TYPES,
    ALLOWED_TOKEN_AUTH_METHODS,
    GRANT_TYPE_AUTHORIZATION_CODE,
    GRANT_TYPE_REFRESH_TOKEN,
    TOKEN_AUTH_NONE,
    OAuthClient,
)
from ..security_scope_contract import allowed_api_key_scopes

CLIENT_ID_PREFIX = "oec"
MAX_REDIRECT_URIS = 10


class OAuthClientRegistrationError(ValueError):
    """Invalid dynamic-registration request (maps to RFC 7591 error payload)."""


def _validate_redirect_uri(uri: str) -> str:
    value = str(uri or "")
    error = "redirect_uri must be https or a loopback http URL without credentials, fragments or invalid ports"
    # urlsplit discards some whitespace/control characters: reject before parsing.
    if any(ord(char) < 33 or ord(char) == 127 for char in value) or "#" in value:
        raise OAuthClientRegistrationError(error)
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if not parsed.hostname or "@" in parsed.netloc or parsed.netloc.endswith(":") or port == 0:
            raise ValueError
        if parsed.netloc.startswith("["):
            suffix = parsed.netloc[parsed.netloc.index("]") + 1:]
            if suffix and not suffix.startswith(":"):
                raise ValueError
    except ValueError:
        # Never echo a rejected URI: it may contain credentials.
        raise OAuthClientRegistrationError(error) from None
    if parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        return value
    raise OAuthClientRegistrationError(error)


def _without_loopback_port(uri: str) -> str | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
        return None
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    authority_start = uri.index("://") + 3
    return uri[:authority_start] + host + uri[authority_start + len(parsed.netloc):]


def _normalize_scopes(raw: Any) -> list[str]:
    if isinstance(raw, str):
        requested = [item for item in raw.split() if item]
    elif isinstance(raw, list):
        requested = [str(item).strip() for item in raw if str(item).strip()]
    else:
        requested = []
    allowed = allowed_api_key_scopes()
    unknown = [scope for scope in requested if scope not in allowed]
    if unknown:
        raise OAuthClientRegistrationError(f"Unknown scopes requested: {unknown}")
    return requested


def _redirect_uris(payload: dict[str, Any]) -> list[str]:
    redirect_uris_raw = payload.get("redirect_uris")
    if not isinstance(redirect_uris_raw, list) or not redirect_uris_raw:
        raise OAuthClientRegistrationError("redirect_uris (non-empty list) is required")
    if len(redirect_uris_raw) > MAX_REDIRECT_URIS:
        raise OAuthClientRegistrationError(f"At most {MAX_REDIRECT_URIS} redirect_uris are allowed")
    return [_validate_redirect_uri(uri) for uri in redirect_uris_raw]


async def register_client(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    registration_source: str = "dynamic",
    created_by: str | None = None,
) -> dict[str, Any]:
    """Register a client and return the RFC 7591 response payload."""
    client_name = str(payload.get("client_name") or "").strip()
    if not client_name:
        raise OAuthClientRegistrationError("client_name is required")
    redirect_uris = _redirect_uris(payload)

    grant_types = payload.get("grant_types") or [GRANT_TYPE_AUTHORIZATION_CODE, GRANT_TYPE_REFRESH_TOKEN]
    unknown_grants = [g for g in grant_types if g not in ALLOWED_GRANT_TYPES]
    if unknown_grants:
        raise OAuthClientRegistrationError(f"Unsupported grant_types: {unknown_grants}")

    auth_method = str(payload.get("token_endpoint_auth_method") or TOKEN_AUTH_NONE)
    if auth_method not in ALLOWED_TOKEN_AUTH_METHODS:
        raise OAuthClientRegistrationError(f"Unsupported token_endpoint_auth_method: {auth_method}")

    scopes = _normalize_scopes(payload.get("scope"))

    client_id = f"{CLIENT_ID_PREFIX}_{secrets.token_urlsafe(24)}"
    client_secret: str | None = None
    client_secret_hash: str | None = None
    if auth_method != TOKEN_AUTH_NONE:
        client_secret = secrets.token_urlsafe(48)
        client_secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt_salt()).decode("utf-8")

    row = OAuthClient(
        client_id=client_id,
        client_secret_hash=client_secret_hash,
        client_name=client_name,
        redirect_uris=redirect_uris,
        grant_types=list(grant_types),
        scopes=scopes,
        token_endpoint_auth_method=auth_method,
        registration_source=registration_source,
        created_by=created_by,
    )
    db.add(row)
    await db.commit()

    response: dict[str, Any] = {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": list(grant_types),
        "token_endpoint_auth_method": auth_method,
    }
    if scopes:
        response["scope"] = " ".join(scopes)
    if client_secret is not None:
        response["client_secret"] = client_secret
    return response


async def get_active_client(db: AsyncSession, client_id: str) -> OAuthClient | None:
    row = (
        await db.execute(
            select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.is_active.is_(True))
        )
    ).scalar_one_or_none()
    return row


def verify_client_secret(client: OAuthClient, client_secret: str | None) -> bool:
    if client.token_endpoint_auth_method == TOKEN_AUTH_NONE:
        return True
    if not client_secret or not client.client_secret_hash:
        return False
    return bcrypt.checkpw(client_secret.encode("utf-8"), client.client_secret_hash.encode("utf-8"))


def redirect_uri_registered(client: OAuthClient, redirect_uri: str) -> bool:
    try:
        requested = _validate_redirect_uri(redirect_uri)
    except OAuthClientRegistrationError:
        return False
    requested_loopback = _without_loopback_port(requested)
    for uri in client.redirect_uris or []:
        try:
            registered = _validate_redirect_uri(uri)
        except OAuthClientRegistrationError:
            continue
        if registered == requested:
            return True
        if requested_loopback is not None and _without_loopback_port(registered) == requested_loopback:
            return True
    return False
