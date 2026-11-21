"""OIDC ID token validation: signature against the provider's JWKS, audience, issuer, expiry and nonce."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from ...models import IdentityProvider

_ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512"]


async def _fetch_jwks(jwks_uri: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(jwks_uri)
        response.raise_for_status()
        return response.json()


async def _decode_id_token_claims(
    *,
    provider: IdentityProvider,
    config: dict[str, Any],
    id_token: str,
    nonce: str,
) -> dict[str, Any]:
    raw_token = str(id_token or "").strip()
    if not raw_token:
        return {}

    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dependency is part of the backend runtime
        raise HTTPException(status_code=500, detail="OIDC ID token validation dependency is unavailable") from exc

    jwks_uri = str(provider.jwks_uri or config.get("jwks_uri") or "").strip()
    if not jwks_uri:
        raise HTTPException(status_code=400, detail="Identity provider is missing JWKS URI for ID token validation")
    jwks = await _fetch_jwks(jwks_uri)
    try:
        token_header = jwt.get_unverified_header(raw_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="OIDC ID token header is invalid") from exc

    key_id = str(token_header.get("kid") or "").strip()
    algorithm = str(token_header.get("alg") or "").strip()
    if algorithm not in _ID_TOKEN_ALGORITHMS:
        raise HTTPException(status_code=400, detail="OIDC ID token uses an unsupported signing algorithm")

    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    matching_key = next(
        (key for key in keys or [] if isinstance(key, dict) and str(key.get("kid") or "").strip() == key_id),
        None,
    )
    if not matching_key:
        raise HTTPException(status_code=400, detail="OIDC ID token signing key was not found in provider JWKS")

    issuer = str(provider.issuer_url or config.get("issuer") or "").strip().rstrip("/")
    decode_kwargs: dict[str, Any] = {
        "algorithms": _ID_TOKEN_ALGORITHMS,
        "audience": str(provider.client_id or "").strip(),
        # PyJWT refuses an iat in the future; python-jose, which this replaced, never did. An identity
        # provider whose clock runs a few seconds ahead would otherwise fail every sign-in. exp, nbf, aud and iss are
        # still checked.
        "options": {"verify_iat": False},
    }
    if issuer:
        decode_kwargs["issuer"] = issuer
    try:
        claims = jwt.decode(raw_token, jwt.PyJWK(matching_key, algorithm=algorithm).key, **decode_kwargs)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="OIDC ID token validation failed") from exc

    expected_nonce = str(nonce or "").strip()
    token_nonce = str(claims.get("nonce") or "").strip()
    if expected_nonce and token_nonce != expected_nonce:
        raise HTTPException(status_code=400, detail="OIDC ID token nonce mismatch")
    return claims
