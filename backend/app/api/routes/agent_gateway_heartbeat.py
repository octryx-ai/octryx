"""Agent gateway: the launcher's heartbeat while Claude Code runs (for Octryx Mobile).

``POST /api/v1/agent-gateway/sessions/heartbeat`` with the session's gateway identity (token, Workspace and session
key headers) moves the presence's own ``heartbeat_at`` (never ``last_seen_at``: an idle open terminal renews no work-
item claims and does not hold off auto-takeover), only on the caller's own presence. The person's phone lists a
session as open only while heartbeats arrive (``session_activity.OPEN_FOR``), so a closed terminal leaves the list
within two minutes.
Transport only; ``{state: "ok"}`` or the gateway's fixed refusal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity
from ...services.agent_gateway.session_activity import note_heartbeat

router = APIRouter(tags=["agent-gateway"])


@router.post("/sessions/heartbeat")
async def heartbeat(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return JSONResponse({"state": identity.state, "reason": identity.reason}, status_code=identity.http_status)
    await note_heartbeat(db, identity.session_key, user_id=identity.user.id)
    await db.commit()
    return {"state": "ok"}


__all__ = ["router"]
