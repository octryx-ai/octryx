"""Octryx Mobile: the phone's side of pairing and its session.

Transport only; the rules live in ``services/mobile`` and ``services/devices/login_validity``.

Pairing (no login yet; each step holds a one-time secret; failures are rate-limited per address):

- ``POST /api/v1/mobile/pairings/scan`` ``{code}`` → ``{pairing_id, scan_secret, match_number, expires_at}``.
- ``POST /api/v1/mobile/pairings/{id}/status`` ``{scan_secret}`` → ``{state: waiting, match_number}`` or, once,
  ``{state: confirmed, claim, claim_expires_at}``.
- ``GET /api/v1/mobile/pairings/{id}`` and ``POST …/{id}/confirm`` ``{approve}``: the person's own signed-in browser
  only (the web session cookie, same origin; no bearer token, API key or phone): it shows the phone and the number
  and confirms or declines. A gateway token (which a tool or an agent on the Mac may hold) never confirms.
- ``POST /api/v1/mobile/claim`` ``{claim, name?}`` → ``{device}``; sets the phone's credential cookie
  (``octryx_mobile``: httpOnly, SameSite=Strict, path ``/api/v1/mobile``) and the phone's own five-minute access cookie
  (``octryx_phone_access``, path ``/``; never the web login's ``access_token``, so one browser keeps both).

Session (the ``octryx_mobile`` cookie, same origin):

- ``POST /api/v1/mobile/session`` → ``{user, device, access_expires_in}`` and a fresh five-minute access cookie;
  a revoked or expired phone gets 401 ``{state, reason}`` and its cookies are cleared.
- ``POST /api/v1/mobile/logout`` → revokes this phone and clears its cookies (``octryx_mobile``,
  ``octryx_phone_access``);
  the web login's ``access_token`` in the same browser is left alone.

The signed-in phone's routes and the admins' validity setting are in ``mobile_account.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE, PHONE_ACCESS_COOKIE_PATH

from ...db import get_db
from ...http_security import API_KEY_HEADER, get_auth_cookie_policy, validate_same_origin_request
from ...models import MobileDevice, User
from ...services.auth import get_current_user
from ...services.auth_rate_limit.service import get_auth_rate_limit_state, register_auth_failure
from ...services.devices.login_validity import login_expires_at, login_validity
from ...services.mobile.contract import (
    ACCESS_TOKEN_TTL,
    MOBILE_COOKIE,
    MOBILE_COOKIE_PATH,
    RATE_SCOPE_CLAIM,
    RATE_SCOPE_PAIRING,
    RATE_SCOPE_SESSION,
    REASON_BODY_INVALID,
    REASON_BROWSER_REQUIRED,
    REASON_NOT_PAIRED,
    REASON_RATE_LIMITED,
)
from ...services.mobile.devices import resolve_phone, revoke_phone, serialize_phone
from ...services.mobile.pairing import claim, confirm, mac_view, owned_pairing, phone_status, scan
from ...services.mobile.session import mint_mobile_access_token, mobile_session_id
from ...time_utils import utc_now_aware
from ._mobile_http import _NO_STORE, _refusal
from .mobile_account import router as account_router

router = APIRouter(tags=["mobile"])
_STATUS = {"mobile_pairing_not_found": 404, "mobile_pairing_expired": 410, "mobile_pairing_used": 409,
           "mobile_pairing_denied": 403, "mobile_claim_invalid": 403}


def _limited(scope: str, request: Request) -> JSONResponse | None:
    state = get_auth_rate_limit_state(scope, request)
    if not state.limited:
        return None
    response = _refusal(REASON_RATE_LIMITED, 429)
    response.headers["Retry-After"] = state.retry_after_header_value
    return response


def _set_phone_cookies(response: JSONResponse, request: Request, *, device: MobileDevice, secret: str | None,
                       max_age: int) -> None:
    policy = get_auth_cookie_policy(request)
    if secret is not None:
        response.set_cookie(MOBILE_COOKIE, secret, httponly=True, secure=policy.secure, samesite="strict",
                            path=MOBILE_COOKIE_PATH, max_age=max(60, max_age))
    response.set_cookie(PHONE_ACCESS_COOKIE,
                        mint_mobile_access_token(user_id=str(device.owner_user_id), device_id=str(device.id)),
                        httponly=True, secure=policy.secure, samesite=policy.samesite, path=PHONE_ACCESS_COOKIE_PATH,
                        max_age=int(ACCESS_TOKEN_TTL.total_seconds()))


def _clear_phone_cookies(response: JSONResponse, request: Request) -> None:
    """The phone's own cookies only: the web login (``access_token``) in the same browser stays signed in."""
    policy = get_auth_cookie_policy(request)
    response.delete_cookie(MOBILE_COOKIE, secure=policy.secure, samesite="strict", path=MOBILE_COOKIE_PATH)
    response.delete_cookie(PHONE_ACCESS_COOKIE, secure=policy.secure, samesite=policy.samesite,
                           path=PHONE_ACCESS_COOKIE_PATH)


async def _seconds_left(db: AsyncSession, device: MobileDevice) -> int:
    expires = login_expires_at(device.created_at, await login_validity(db))
    return int((expires - utc_now_aware()).total_seconds())


# --- pairing --------------------------------------------------------------------------------------------------


@router.post("/api/v1/mobile/pairings/scan")
async def scan_code(request: Request, body: Any = Body(None), db: AsyncSession = Depends(get_db)):
    if (limited := _limited(RATE_SCOPE_PAIRING, request)) is not None:
        return limited
    code = body.get("code") if isinstance(body, dict) else None
    result = await scan(db, code=code, user_agent=str(request.headers.get("user-agent") or ""))
    if isinstance(result, str):
        register_auth_failure(RATE_SCOPE_PAIRING, request)
        return _refusal(result, _STATUS.get(result, 400))
    await db.commit()
    return JSONResponse({"pairing_id": result.pairing.id, "scan_secret": result.scan_secret,
                         "match_number": result.pairing.match_number,
                         "expires_at": result.pairing.expires_at.isoformat() + "Z"}, headers=_NO_STORE)


@router.post("/api/v1/mobile/pairings/{pairing_id}/status")
async def pairing_status(pairing_id: str, request: Request, body: Any = Body(None), db: AsyncSession = Depends(get_db)):
    if (limited := _limited(RATE_SCOPE_PAIRING, request)) is not None:
        return limited
    secret = body.get("scan_secret") if isinstance(body, dict) else None
    result = await phone_status(db, pairing_id=pairing_id[:40], scan_secret=secret)
    if isinstance(result, str):
        if result == "mobile_pairing_not_found":
            register_auth_failure(RATE_SCOPE_PAIRING, request)
        return _refusal(result, _STATUS.get(result, 400))
    await db.commit()
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/api/v1/mobile/claim")
async def claim_phone(request: Request, body: Any = Body(None), db: AsyncSession = Depends(get_db)):
    validate_same_origin_request(request)
    if (limited := _limited(RATE_SCOPE_CLAIM, request)) is not None:
        return limited
    if not isinstance(body, dict):
        return _refusal(REASON_BODY_INVALID, 400)
    result = await claim(db, claim_token=body.get("claim"), name=str(body.get("name") or ""))
    if isinstance(result, str):
        register_auth_failure(RATE_SCOPE_CLAIM, request)
        return _refusal(result, _STATUS.get(result, 400))
    device, secret = result
    seconds = await _seconds_left(db, device)
    await db.commit()
    response = JSONResponse({"device": serialize_phone(device, validity=await login_validity(db),
                                                       current_id=device.id)}, status_code=201, headers=_NO_STORE)
    _set_phone_cookies(response, request, device=device, secret=secret, max_age=seconds)
    return response


# --- confirmation in the person's signed-in browser (never with a gateway token or a phone) -------------------

_CONFIRM_STATUS = {"mobile_pairing_expired": 410, "mobile_pairing_not_scanned": 409, "mobile_pairing_used": 409}


def _browser_refusal(request: Request) -> JSONResponse | None:
    """Only the web session's own cookie confirms: no bearer token, no API key, no phone."""
    cookie = str(request.cookies.get(ACCESS_TOKEN_COOKIE) or "")
    if (not cookie or request.headers.get("authorization") or request.headers.get(API_KEY_HEADER)
            or mobile_session_id(cookie)):
        return _refusal(REASON_BROWSER_REQUIRED, 403)
    return None


@router.get("/api/v1/mobile/pairings/{pairing_id}")
async def pairing_to_confirm(pairing_id: str, request: Request, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    if (refused := _browser_refusal(request)) is not None:
        return refused
    pairing = await owned_pairing(db, pairing_id=pairing_id[:40], user_id=str(current_user.id))
    if isinstance(pairing, str):
        return _refusal(pairing, 404)
    return JSONResponse(mac_view(pairing), headers=_NO_STORE)


@router.post("/api/v1/mobile/pairings/{pairing_id}/confirm")
async def confirm_in_browser(pairing_id: str, request: Request, body: Any = Body(None),
                             current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_same_origin_request(request)
    if (refused := _browser_refusal(request)) is not None:
        return refused
    if not isinstance(body, dict) or type(body.get("approve")) is not bool:
        return _refusal(REASON_BODY_INVALID, 400)
    pairing = await owned_pairing(db, pairing_id=pairing_id[:40], user_id=str(current_user.id))
    if isinstance(pairing, str):
        return _refusal(pairing, 404)
    refusal = await confirm(db, pairing=pairing, user_id=str(current_user.id), approve=body["approve"])
    if refusal:
        return _refusal(refusal, _CONFIRM_STATUS.get(refusal, 409))
    await db.commit()
    return JSONResponse(mac_view(pairing), headers=_NO_STORE)


# --- session --------------------------------------------------------------------------------------------------


@router.post("/api/v1/mobile/session")
async def phone_session(request: Request, db: AsyncSession = Depends(get_db)):
    validate_same_origin_request(request)
    if (limited := _limited(RATE_SCOPE_SESSION, request)) is not None:
        return limited
    secret = str(request.cookies.get(MOBILE_COOKIE) or "")
    device = await resolve_phone(db, secret) if secret else REASON_NOT_PAIRED
    if isinstance(device, str):
        if secret:
            register_auth_failure(RATE_SCOPE_SESSION, request)
        response = _refusal(device, 401, state="unauthorized")
        _clear_phone_cookies(response, request)
        return response
    user = await db.get(User, device.owner_user_id)
    validity = await login_validity(db)
    seconds = await _seconds_left(db, device)
    await db.commit()
    response = JSONResponse({
        "user": {"id": str(user.id), "name": user.display_name or user.username},
        "device": serialize_phone(device, validity=validity, current_id=device.id),
        "access_expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
    }, headers=_NO_STORE)
    _set_phone_cookies(response, request, device=device, secret=None, max_age=seconds)
    return response


@router.post("/api/v1/mobile/logout")
async def phone_logout(request: Request, db: AsyncSession = Depends(get_db)):
    validate_same_origin_request(request)
    secret = str(request.cookies.get(MOBILE_COOKIE) or "")
    device = await resolve_phone(db, secret) if secret else REASON_NOT_PAIRED
    if not isinstance(device, str):
        await revoke_phone(db, device, actor_id=str(device.owner_user_id), reason="signed out on the phone")
        await db.commit()
    response = JSONResponse({"state": "signed_out"}, headers=_NO_STORE)
    _clear_phone_cookies(response, request)
    return response


# Included after the routes above so the registration order stays the same.
router.include_router(account_router)

__all__ = ["router"]
