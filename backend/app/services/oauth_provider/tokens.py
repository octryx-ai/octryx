"""Access-token mint/verify for the platform OAuth authorization server."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import jwt

from ...config import get_settings

OAUTH_TOKEN_ISSUER = "octryx-oauth"
DEFAULT_RESOURCE_AUDIENCE = "octryx-mcp"


def _settings():
    return get_settings()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mint_access_token(
    *,
    user_id: str,
    client_id: str,
    grant_id: str,
    scopes: list[str],
    resource: str | None,
    expires_minutes: int | None = None,
) -> tuple[str, int]:
    """Return (jwt, expires_in_seconds)."""
    settings = _settings()
    from ...time_utils import utc_now

    minutes = expires_minutes or settings.jwt_expire_minutes
    expires_at = utc_now() + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "client_id": client_id,
        "grant_id": grant_id,
        "scope": " ".join(scopes),
        "aud": resource or DEFAULT_RESOURCE_AUDIENCE,
        "iss": OAUTH_TOKEN_ISSUER,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, minutes * 60


def verify_access_token(token: str, *, audience: str = DEFAULT_RESOURCE_AUDIENCE) -> dict[str, Any] | None:
    """Validate an OAuth access token; return claims or None."""
    settings = _settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=audience,
            issuer=OAUTH_TOKEN_ISSUER,
        )
    except jwt.PyJWTError:
        return None


def verify_access_token_for_audiences(token: str, *, audiences: set[str]) -> dict[str, Any] | None:
    settings = _settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=OAUTH_TOKEN_ISSUER,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        return None
    if str(claims.get("aud") or "") not in audiences:
        return None
    return claims
