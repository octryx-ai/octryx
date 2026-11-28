"""Octryx Mobile live: the owner's view of the Claude Code sessions running on their devices."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.live_values import LiveError

from ....db import get_db
from ....http_security import API_KEY_HEADER, validate_same_origin_request
from ....models import User
from ....services.auth import get_current_user
from ....services.devices.live import conversation, overview, queue_message, serialize_message

router = APIRouter(tags=["mobile"])
_NO_STORE = {"cache-control": "no-store"}


def _refusal(reason: str, status: int) -> JSONResponse:
    return JSONResponse({"state": "denied", "reason": reason}, status_code=status, headers=_NO_STORE)


def _interactive_refusal(request: Request) -> JSONResponse | None:
    if (getattr(request.state, "api_key_id", None) or request.headers.get(API_KEY_HEADER)
            or request.headers.get("authorization")):
        return _refusal("interactive_login_required", 403)
    return None


@router.get("/api/v1/mobile/live")
async def live_sessions(request: Request, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    if refusal := _interactive_refusal(request):
        return refusal
    return JSONResponse({"items": await overview(db, current_user)}, headers=_NO_STORE)


@router.get("/api/v1/mobile/live/messages")
async def live_messages(request: Request, device_id: str = Query(..., min_length=1, max_length=40),
                        peer: str = Query(..., min_length=1, max_length=300),
                        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if refusal := _interactive_refusal(request):
        return refusal
    try:
        answer = await conversation(db, current_user, device_id=device_id, peer=peer)
    except LiveError as error:
        return _refusal(error.reason, error.status)
    from ....services.attention.device_items import mark_live_read  # noqa: PLC0415

    await mark_live_read(db, current_user, device_id=device_id, peer=peer)  # read: the answer no longer needs you
    await db.commit()
    return JSONResponse(answer, headers=_NO_STORE)


@router.post("/api/v1/mobile/live/fork")
async def fork_live_session(request: Request, body: Any = Body(None), current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """``{device_id, peer, message}``: continue a copy of an idle listed session as a Mac chat."""
    if refusal := _interactive_refusal(request):
        return refusal
    validate_same_origin_request(request)
    payload = body if isinstance(body, dict) else {}
    from ....services.devices.live import fork_session  # noqa: PLC0415

    try:
        started = await fork_session(db, current_user, device_id=str(payload.get("device_id") or "")[:40],
                                     peer=str(payload.get("peer") or "")[:300], message=payload.get("message"))
    except LiveError as error:
        await db.rollback()
        return _refusal(error.reason, error.status)
    await db.commit()
    return JSONResponse(started, status_code=201, headers=_NO_STORE)


@router.get("/api/v1/mobile/live/progress")
async def live_progress(request: Request, device_id: str = Query(..., min_length=1, max_length=40),
                        peer: str = Query(..., min_length=1, max_length=300),
                        since_seq: int = Query(default=0, ge=0, le=2_000_000_000),
                        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What a listed session is doing; ``since_seq``: only what is newer (catch-up)."""
    if refusal := _interactive_refusal(request):
        return refusal
    from ....services.devices.live_progress import progress  # noqa: PLC0415

    try:
        answer = await progress(db, current_user, device_id=device_id, peer=peer, since_seq=since_seq)
    except LiveError as error:
        return _refusal(error.reason, error.status)
    return JSONResponse(answer, headers=_NO_STORE)


@router.post("/api/v1/mobile/live/messages")
async def send_live_message(request: Request, body: Any = Body(None), current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    if refusal := _interactive_refusal(request):
        return refusal
    validate_same_origin_request(request)
    payload = body if isinstance(body, dict) else {}
    try:
        message = await queue_message(db, current_user, device_id=str(payload.get("device_id") or "")[:40],
                                      peer=str(payload.get("peer") or "")[:300], text=payload.get("text"),
                                      images=payload.get("images"))
    except LiveError as error:  # refused before anything was written
        return _refusal(error.reason, error.status)
    await db.commit()
    return JSONResponse({"message": serialize_message(message)}, status_code=202, headers=_NO_STORE)


__all__ = ["router"]
