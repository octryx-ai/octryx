"""Agent gateway: the launcher registers its per-session hook key.

Transport only. ``POST /api/v1/agent-gateway/sessions/hook-key`` takes the gateway identity
(token, Workspace and launcher session key) and the body ``{"hook_key", "state_root"}``. The key is
set once per session (``services/agent_gateway/hook_key``): the launcher registers it before
Claude Code starts, so nothing started later can replace it. The answer never echoes the key.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.agent_gateway.contract import STATE_DENIED
from ...services.agent_gateway.hook_key import REASON_HOOK_KEY_ALREADY_REGISTERED, register_hook_key
from ...services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity
from ...services.agent_gateway.sessions import get_or_create_gateway_session
from ._agent_gateway_http import _bounded_json, _from_refusal, _refusal

router = APIRouter(prefix="/api/v1/agent-gateway/sessions", tags=["agent-gateway"])

MAX_HOOK_KEY_BODY_BYTES = 4 * 1024


@router.post("/hook-key")
async def register_session_hook_key(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    body = await _bounded_json(request, MAX_HOOK_KEY_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    session = await get_or_create_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    refused = await register_hook_key(
        db, session=session, raw_key=body.get("hook_key"), raw_state_root=body.get("state_root")
    )
    if refused is not None:
        return _refusal(STATE_DENIED, refused, 409 if refused == REASON_HOOK_KEY_ALREADY_REGISTERED else 400)
    await db.commit()
    return {"state": "registered"}
