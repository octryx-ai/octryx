"""Agent gateway: the Mac's side of pairing a phone (``octryx-claude mobile pair``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import get_settings
from ....db import get_db
from ....models import User
from ....models.security.oauth_provider import OAuthGrant
from ....services.agent_gateway.identity import GatewayRefusal, resolve_gateway_login
from ....services.devices.contract import REASON_LOGIN_REQUIRED, STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ....services.mobile.contract import REASON_LOGIN_REQUIRED as REASON_LOGIN_REQUIRED_MOBILE
from ....services.mobile.contract import REASON_TOO_MANY
from ....services.mobile.pairing import confirm_url, create_pairing, mac_view, owned_pairing, pair_url
from ....services.oauth_provider.flows import _login_session_alive

router = APIRouter(tags=["agent-gateway"])
# The scopes of the person's own octryx-claude login (the launcher's login), beyond model calls.
PAIRING_SCOPES = frozenset({"model:invoke", "knowledge:read", "work:manage"})
REASON_SCOPE_MISSING = "mobile_pairing_scope_missing"
_NO_STORE = {"cache-control": "no-store"}


def _refusal(state: str, reason: str, status: int) -> JSONResponse:
    return JSONResponse({"state": state, "reason": reason}, status_code=status, headers=_NO_STORE)


async def _login(request: Request, db: AsyncSession) -> tuple[User, str] | JSONResponse:
    login = await resolve_gateway_login(db, request.headers)
    if isinstance(login, GatewayRefusal):
        return _refusal(login.state, login.reason, login.http_status)
    user, context = login
    grant = await db.get(OAuthGrant, context.grant_id)
    if grant is None or grant.device_id:
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_LOGIN_REQUIRED, 403)
    # Only a full octryx-claude login pairs a phone; a token for model calls alone (an apiKeyHelper token handed to
    # a tool, a self-registered OAuth client) does not.
    if not PAIRING_SCOPES <= set(context.scopes or ()):
        return _refusal(STATE_DENIED, REASON_SCOPE_MISSING, 403)
    # The login must still be tied to a live web login: the phone will live only as long as both do.
    if not await _login_session_alive(db, grant.platform_refresh_token_id):
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_LOGIN_REQUIRED_MOBILE, 403)
    return user, grant.id


def _base_url(request: Request) -> str:
    configured = str(get_settings().platform_public_origin or "").strip()
    return configured or str(request.base_url)


@router.post("/mobile/pairings")
async def start_pairing(request: Request, db: AsyncSession = Depends(get_db)):
    login = await _login(request, db)
    if isinstance(login, JSONResponse):
        return login
    user, grant_id = login
    created = await create_pairing(db, user_id=str(user.id), grant_id=grant_id)
    if isinstance(created, str):
        return _refusal(STATE_DENIED, REASON_TOO_MANY, 429)
    pairing, code = created
    await db.commit()
    return JSONResponse({"pairing_id": pairing.id, "url": pair_url(_base_url(request), code),
                         "confirm_url": confirm_url(_base_url(request), pairing.id),
                         "expires_at": mac_view(pairing)["expires_at"]}, status_code=201, headers=_NO_STORE)


@router.get("/mobile/pairings/{pairing_id}")
async def pairing_view(pairing_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    login = await _login(request, db)
    if isinstance(login, JSONResponse):
        return login
    user, _grant_id = login
    pairing = await owned_pairing(db, pairing_id=pairing_id[:40], user_id=str(user.id))
    if isinstance(pairing, str):
        return _refusal(STATE_DENIED, pairing, 404)
    return JSONResponse(mac_view(pairing), headers=_NO_STORE)


__all__ = ["router"]
