"""Agent gateway: one batch of an octryx-claude session's full transcript (behind a Workspace switch)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.agent_gateway.contract import HEADER_GATEWAY_REASON, HEADER_GATEWAY_STATE, STATE_DENIED
from ....services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity
from ....services.agent_gateway.sessions import find_gateway_session
from ....services.session_transcripts.store import REASON_INVALID, TranscriptBatch, TranscriptBatchError, store_batch

router = APIRouter(tags=["agent-gateway"])

# A batch carries whole transcript lines, file contents included (that is the switch's point).
MAX_TRANSCRIPT_BODY_BYTES = 16 * 1024 * 1024
REASON_BODY_TOO_LARGE = "request_body_too_large"


def _refusal(state: str, reason: str, status: int) -> JSONResponse:
    return JSONResponse({"state": state, "reason": reason}, status_code=status,
                        headers={HEADER_GATEWAY_STATE: state, HEADER_GATEWAY_REASON: reason})


async def _body(request: Request) -> dict[str, Any] | None:
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > MAX_TRANSCRIPT_BODY_BYTES:
            raise OverflowError
    try:
        body = json.loads(bytes(received) or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


@router.post("/sessions/transcript")
async def transcript_batch(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _refusal(identity.state, identity.reason, identity.http_status)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _refusal(session.state, session.reason, session.http_status)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_TRANSCRIPT_BODY_BYTES:
        return _refusal(STATE_DENIED, REASON_BODY_TOO_LARGE, 413)
    try:
        body = await _body(request)
    except OverflowError:
        return _refusal(STATE_DENIED, REASON_BODY_TOO_LARGE, 413)
    try:
        batch = TranscriptBatch.from_body(body or {})
    except TranscriptBatchError:
        return _refusal(STATE_DENIED, REASON_INVALID, 400)
    result = await store_batch(db, session=session, batch=batch)
    await db.commit()
    return result


__all__ = ["MAX_TRANSCRIPT_BODY_BYTES", "router"]
