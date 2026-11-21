"""Who a request is for the rate limiter: a verified user, or nobody (then the client address).

The limiter runs before any route resolves the caller, so it verifies the credential itself, in process and
without a database round trip, exactly as the platform would accept it:

- a platform session token (``Authorization: Bearer`` or, without a bearer, the ``access_token`` cookie or a
  phone's ``octryx_phone_access`` cookie, chosen by ``services.auth.service.cookie_access_token``):
  signature, audience, issuer and expiry, as ``services.auth.decode_token`` checks them -> ``user:<id>``;
- a platform OAuth access token (MCP clients): signature, issuer and expiry -> ``user:<id>:grant:<grant>``,
  so each grant of a user has its own budget.

Everything else is anonymous: no credential, a forged, expired or wrongly signed token, an API key or a gateway
login token (those need the database), and the seat route's subscription bearer, which is never decoded
An anonymous request is limited per client address, so a forged token can never select a fresh
per-user bucket. Nothing here logs or returns a token.
"""

from __future__ import annotations

import jwt
from fastapi import HTTPException, Request

from ...config import get_settings
from ...services.agent_gateway.contract import SEAT_MODEL_ROUTE_PREFIXES
from ...services.auth import decode_token
from ...services.auth.service import cookie_access_token
from ...services.oauth_provider.tokens import OAUTH_TOKEN_ISSUER

_MAX_TOKEN_CHARS = 8192


def _presented_token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    return cookie_access_token(request)


def _oauth_principal(token: str) -> str | None:
    try:
        claims = jwt.decode(
            token, get_settings().jwt_secret, algorithms=["HS256"], issuer=OAUTH_TOKEN_ISSUER,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        return None
    user_id, grant_id = str(claims.get("sub") or "").strip(), str(claims.get("grant_id") or "").strip()
    return f"user:{user_id}:grant:{grant_id}" if user_id and grant_id else None


def request_principal(request: Request) -> str | None:
    """The verified principal key of the request, or ``None`` (anonymous: keyed by client address)."""
    if request.url.path.startswith(SEAT_MODEL_ROUTE_PREFIXES):
        return None
    token = _presented_token(request)
    if not token or len(token) > _MAX_TOKEN_CHARS:
        return None
    try:
        user_id = str(decode_token(token, allow_phone=True) or "").strip()  # identity only, not access
    except HTTPException:
        return _oauth_principal(token)
    return f"user:{user_id}" if user_id else None


__all__ = ["request_principal"]
