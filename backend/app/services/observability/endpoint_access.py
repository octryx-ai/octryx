"""Who may read the runtime endpoints (O0)."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from ...config import get_settings
from ..auth.service import get_current_user


def _bearer(request: Request) -> str:
    scheme, _, value = str(request.headers.get("authorization") or "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def scrape_token_matches(request: Request) -> bool:
    configured = str(get_settings().metrics_scrape_token or "").strip()
    presented = _bearer(request)
    return bool(configured and presented) and hmac.compare_digest(configured.encode(), presented.encode())


async def caller_is_signed_in(request: Request) -> bool:
    factory = request.app.state.async_session_factory
    token = _bearer(request)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token) if token else None
    async with factory() as db:
        try:
            await get_current_user(request, credentials, db)
        except HTTPException:
            return False
    return True


async def require_metrics_reader(request: Request) -> None:
    if scrape_token_matches(request) or await caller_is_signed_in(request):
        return
    raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


async def health_body_for(request: Request, full: dict[str, Any]) -> dict[str, Any]:
    if await caller_is_signed_in(request):
        return full
    return {"status": full.get("status")}
