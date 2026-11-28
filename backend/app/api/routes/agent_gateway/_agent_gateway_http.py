"""Shared transport helpers of the agent gateway route modules: fixed refusals, the bounded JSON body, and the gateway
identity with its shadow session."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ....services.agent_gateway.contract import HEADER_GATEWAY_REASON, HEADER_GATEWAY_STATE
from ....services.agent_gateway.identity import GatewayIdentity, GatewayRefusal, resolve_gateway_identity
from ....services.agent_gateway.presence import touch_presence
from ....services.agent_gateway.sessions import find_gateway_session

REASON_BODY_TOO_LARGE = "request_body_too_large"
REASON_BODY_INVALID = "request_body_invalid"
REASON_HOOK_EVENT_UNSUPPORTED = "hook_event_unsupported"
REASON_POLICY_INVALID = "policy_invalid"


def _refusal(state: str, reason: str, status: int, **extra: Any) -> JSONResponse:
    return JSONResponse(
        {"state": state, "reason": reason, **extra},
        status_code=status,
        headers={HEADER_GATEWAY_STATE: state, HEADER_GATEWAY_REASON: reason},
    )


def _from_refusal(refusal: GatewayRefusal, **extra: Any) -> JSONResponse:
    return _refusal(refusal.state, refusal.reason, refusal.http_status, **extra)


async def _bounded_json(request: Request, limit: int) -> dict[str, Any] | tuple[str, int]:
    # The limit is checked after each chunk, so an oversized body is refused before JSON decoding.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        return REASON_BODY_TOO_LARGE, 413
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > limit:
            return REASON_BODY_TOO_LARGE, 413
    try:
        body = json.loads(bytes(received) or b"{}")
    except ValueError:
        return REASON_BODY_INVALID, 400
    return body if isinstance(body, dict) else (REASON_BODY_INVALID, 400)


async def _identity_and_session(request: Request, db: AsyncSession) -> tuple[GatewayIdentity, Session] | GatewayRefusal:
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return identity
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return session
    # Every hook call is a sign of life of the session's presence.
    await touch_presence(db, identity.session_key)
    await db.commit()
    return identity, session
