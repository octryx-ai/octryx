"""MASH OAuth2 client-credentials auth service."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

import bcrypt
import jwt

from ....bcrypt_cost import bcrypt_salt
from ....config import get_settings
from ....time_utils import utc_now

settings = get_settings()

MASH_JWT_ALGORITHM = "HS256"
MASH_TOKEN_TTL_SECONDS = 3600  # 1 hour
MASH_JWT_ISSUER = "mash-master"
MASH_JWT_AUDIENCE = "mash-platform"

MASH_SCOPES = frozenset({
    "policies:read",
    "audit:write",
    "stats:write",
    "peer:call",
    "platform:register",
})


def hash_client_secret(secret: str) -> str:
    return bcrypt.hashpw(secret.encode("utf-8"), bcrypt_salt()).decode("utf-8")


def verify_client_secret(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def generate_client_credentials() -> tuple[str, str]:
    client_id = f"mash_plat_{secrets.token_hex(12)}"
    client_secret = f"mash_sec_{secrets.token_urlsafe(32)}"
    return client_id, client_secret


def create_access_token(
    platform_id: str,
    scopes: list[str],
    ttl_seconds: int = MASH_TOKEN_TTL_SECONDS,
) -> str:
    now = utc_now()
    payload: dict[str, Any] = {
        "sub": platform_id,
        "scopes": scopes,
        "iss": MASH_JWT_ISSUER,
        "aud": MASH_JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=MASH_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[MASH_JWT_ALGORITHM],
        audience=MASH_JWT_AUDIENCE,
        issuer=MASH_JWT_ISSUER,
    )


def validate_scopes(requested: list[str]) -> list[str]:
    return [s for s in requested if s in MASH_SCOPES]


def token_has_scope(token_payload: dict[str, Any], required_scope: str) -> bool:
    scopes = token_payload.get("scopes", [])
    return required_scope in scopes
