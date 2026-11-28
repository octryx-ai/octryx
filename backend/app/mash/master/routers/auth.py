"""MASH OAuth2 token endpoint and auth dependencies."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from ....db import get_db
from ..models import MashPlatformCredential
from ..services.auth_service import (
    create_access_token,
    decode_access_token,
    token_has_scope,
    validate_scopes,
    verify_client_secret,
)

router = APIRouter(prefix="/mash", tags=["mash-auth"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class TokenRequest(BaseModel):
    grant_type: str
    client_id: str
    client_secret: str
    scope: str | None = None


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


@router.post("/oauth/token")
async def mash_token(payload: TokenRequest, db: AsyncSession = Depends(get_db)):
    if payload.grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    result = await db.execute(
        select(MashPlatformCredential).where(
            MashPlatformCredential.client_id == payload.client_id,
            MashPlatformCredential.revoked_at.is_(None),
        )
    )
    cred = result.scalar_one_or_none()
    if not cred or not verify_client_secret(payload.client_secret, cred.client_secret_hash):
        raise HTTPException(status_code=401, detail="invalid_client")

    # Determine scopes
    requested = payload.scope.split() if payload.scope else []
    granted = validate_scopes(requested) if requested else list(cred.scopes or [])

    # Ensure requested scopes are within the credential's allowed scopes
    allowed = set(cred.scopes or [])
    granted = [s for s in granted if s in allowed]

    token = create_access_token(
        platform_id=cred.platform_id,
        scopes=granted,
    )

    return JSONResponse({
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": " ".join(granted),
    })


# ---------------------------------------------------------------------------
# Auth dependency for MASH routes
# ---------------------------------------------------------------------------


async def require_mash_token(request: Request) -> dict[str, Any]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_token")
    token = auth[7:]
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid_token")
    return payload


def require_scope(scope: str):
    async def _check(token: dict[str, Any] = Depends(require_mash_token)):
        if not token_has_scope(token, scope):
            raise HTTPException(status_code=403, detail=f"scope_required:{scope}")
        return token
    return _check
