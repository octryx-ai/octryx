"""Octryx Mobile: the signed-in phone's devices, usage, sessions and notifications, and the login validity."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE

from ....db import get_db
from ....http_security import API_KEY_HEADER, validate_same_origin_request
from ....models import MobileDevice, User
from ....services.access_control import get_project_role_for_user
from ....services.admin.governance.admin_access_service import is_global_admin
from ....services.agent_gateway.session_activity import open_sessions
from ....services.agent_gateway.usage_read import own_gateway_usage
from ....services.auth import get_current_user
from ....services.devices.local_sessions import LocalSessionError, list_for_owner, take_over
from ....services.devices.login_validity import (
    REASON_VALIDITY_INVALID,
    login_validity,
    login_validity_text,
    set_login_validity,
)
from ....services.mobile.contract import REASON_NOT_PAIRED
from ....services.mobile.devices import list_phones, owned_phone, phone_refusal, revoke_phone, serialize_phone
from ....services.mobile.push import phone_subscription, push_state, set_rules, subscribe, unsubscribe
from ....services.mobile.session import request_phone_id
from ._mobile_http import _NO_STORE, _refusal

router = APIRouter()



@router.get("/api/v1/mobile/devices")
async def my_phones(request: Request, current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    validity = await login_validity(db)
    current = request_phone_id(request, user_id=str(current_user.id))
    phones = await list_phones(db, owner_user_id=str(current_user.id))
    return JSONResponse({"items": [serialize_phone(phone, validity=validity, current_id=current) for phone in phones],
                         "login_validity": await login_validity_text(db)}, headers=_NO_STORE)


@router.post("/api/v1/mobile/devices/{device_id}/revoke")
async def revoke_my_phone(device_id: str, request: Request, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    validate_same_origin_request(request)
    phone = await owned_phone(db, owner_user_id=str(current_user.id), device_id=device_id[:40])
    if isinstance(phone, str):
        return _refusal(phone, 404)
    await revoke_phone(db, phone, actor_id=str(current_user.id), reason="revoked by the owner")
    await db.commit()
    return JSONResponse({"state": "revoked", "device_id": phone.id}, headers=_NO_STORE)


@router.get("/api/v1/mobile/usage")
async def my_usage(workspace_id: str = Query(..., min_length=1, max_length=64),
                   current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if await get_project_role_for_user(db, current_user.id, workspace_id) is None:
        return _refusal("workspace_not_found", 404)
    usage = await own_gateway_usage(db, user_id=str(current_user.id), workspace_id=workspace_id)
    return JSONResponse(usage, headers=_NO_STORE)


@router.get("/api/v1/mobile/sessions")
async def my_open_sessions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The person's own open octryx-claude sessions (terminal, VS Code) with what they are doing."""
    return JSONResponse({"items": await open_sessions(db, user_id=str(current_user.id))}, headers=_NO_STORE)


def _interactive_refusal(request: Request) -> JSONResponse | None:
    # A leaked CI or MCP key must not become a shell on the person's Mac.
    if request.headers.get(API_KEY_HEADER) or request.headers.get("authorization"):
        return _refusal("interactive_login_required", 403)
    if not (request.cookies.get(ACCESS_TOKEN_COOKIE) or request.cookies.get(PHONE_ACCESS_COOKIE)):
        return _refusal("interactive_login_required", 403)
    return None


@router.get("/api/v1/mobile/local-sessions")
async def my_local_sessions(request: Request, current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """The person's Claude Code sessions outside octryx, as their own devices report them (owner only)."""
    if (refused := _interactive_refusal(request)) is not None:
        return refused
    return JSONResponse({"items": await list_for_owner(db, user_id=str(current_user.id))}, headers=_NO_STORE)


@router.post("/api/v1/mobile/local-sessions/{local_id}/messages")
async def take_over_local_session(local_id: str, request: Request, body: Any = Body(None),
                                  current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """``{message}``: the next turn of that Claude Code session, run on its device in the private Workspace."""
    validate_same_origin_request(request)
    if (refused := _interactive_refusal(request)) is not None:
        return refused
    message = body.get("message") if isinstance(body, dict) else None
    thread_id = body.get("thread_id") if isinstance(body, dict) and isinstance(body.get("thread_id"), str) else ""
    try:  # ``thread_id``: the next turn of a fork of that session
        started = await take_over(db, user=current_user, local_id=local_id, prompt=message, thread_id=thread_id)
    except LocalSessionError as refused:
        await db.rollback()
        return _refusal(refused.reason, refused.status)
    await db.commit()
    return JSONResponse(started, status_code=201, headers=_NO_STORE)



async def _this_phone(request: Request, db: AsyncSession, user: User) -> MobileDevice | None:
    if request.headers.get("authorization") or request.headers.get(API_KEY_HEADER):
        return None
    device_id = request_phone_id(request, user_id=str(user.id))
    device = await db.get(MobileDevice, device_id) if device_id else None
    if device is None or str(device.owner_user_id) != str(user.id) or await phone_refusal(db, device):
        return None
    return device


@router.get("/api/v1/mobile/push")
async def push_settings(request: Request, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    phone = await _this_phone(request, db, current_user)
    subscription = await phone_subscription(db, phone.id) if phone is not None else None
    return JSONResponse(push_state(subscription), headers=_NO_STORE)


@router.put("/api/v1/mobile/push")
async def push_subscribe(request: Request, body: Any = Body(None), current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """``{subscription: {endpoint, keys: {p256dh, auth}}, rules?}`` subscribes this phone; ``{rules}`` alone sets
    which groups it wants (needs_you, problem, done)."""
    validate_same_origin_request(request)
    phone = await _this_phone(request, db, current_user)
    if phone is None:
        return _refusal(REASON_NOT_PAIRED, 403)
    if isinstance(body, dict) and "subscription" not in body:
        row = await set_rules(db, phone, body.get("rules"))
    else:
        row = await subscribe(db, phone, body)
        if isinstance(row, str):
            return _refusal(row, 409 if row == "mobile_push_not_configured" else 400)
    await db.commit()
    return JSONResponse(push_state(row), headers=_NO_STORE)


@router.delete("/api/v1/mobile/push")
async def push_unsubscribe(request: Request, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    validate_same_origin_request(request)
    phone = await _this_phone(request, db, current_user)
    if phone is not None:
        await unsubscribe(db, phone)
        await db.commit()
    return JSONResponse(push_state(None), headers=_NO_STORE)


# Platform admins only: the device login validity.


@router.get("/api/v1/admin/devices/login-validity")
async def get_validity(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    return {"validity": await login_validity_text(db), "min": "1h", "max": "365d"}


@router.put("/api/v1/admin/devices/login-validity")
async def put_validity(request: Request, body: Any = Body(None), current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    validate_same_origin_request(request)
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    value = body.get("validity") if isinstance(body, dict) else None
    try:
        stored = await set_login_validity(db, value=value, actor_id=str(current_user.id))
    except ValueError:
        return _refusal(REASON_VALIDITY_INVALID, 400)
    await db.commit()
    return {"validity": stored, "min": "1h", "max": "365d"}
