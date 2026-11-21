"""Remote device sessions: device registration and management.

Transport only; the rules live in ``services/devices`` (``registry``, ``credential``).

- ``POST /api/v1/devices`` — ``octryx-claude device enable`` with its gateway login token registers the device
  and receives the device credential once (``cache-control: no-store``).
- ``POST /api/v1/devices/self/disable`` — the device, with its own channel token, revokes itself
  (``device disable``).
- ``POST /api/v1/devices/self/renew`` — the device renews its credential with a request signed by its device key
  (``services/devices/renewal``); no login, refused for a revoked device or a foreign key.
- ``GET /api/v1/devices`` — My settings → Devices and the chat target picker: the caller's own devices only.
- ``PATCH /api/v1/devices/{id}`` — rename, narrow folders, pause/resume (owner only).
- ``POST /api/v1/devices/{id}/revoke`` — owner revoke.
- ``PUT /api/v1/devices/pause`` — "Pause all my devices" (personal kill switch).
- ``GET /api/v1/admin/devices`` / ``POST /api/v1/admin/devices/{id}/revoke`` — platform admins see devices
  (without folders, D12) and can revoke one with a reason. They can never send a device work.

A refusal is ``{state, reason}`` with a fixed code; another user's device answers ``device_not_found``.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_state import STATUS_RUNNING
from app.services.devices.registry_values import DeviceRegistryError
from app.services.devices.registry_view import serialize_device

from ...db import get_db
from ...models import DeviceJob, User, UserDevice
from ...models.security.oauth_provider import OAuthGrant
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.agent_gateway.identity import GatewayRefusal, bearer_token, resolve_gateway_login
from ...services.auth import get_current_user
from ...services.devices.contract import (
    DEVICE_AUDIENCE,
    REASON_DEVICE_NOT_FOUND,
    REASON_LOGIN_REQUIRED,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
    STATE_UNAUTHORIZED,
)
from ...services.devices.credential import devices_needing_login, resolve_device_credential
from ...services.devices.hub import device_live_state, device_revoked, devices_paused
from ...services.devices.login_validity import login_expires_at, login_validity
from ...services.devices.registry import (
    list_devices,
    narrow_folders,
    owned_device,
    register_device,
    rename_device,
    revoke_device,
    set_paused,
)
from ...services.devices.renewal import renew_device_credential

router = APIRouter(tags=["devices"])

REASON_ADMIN_REQUIRED = "platform_admin_required"
REASON_BODY_INVALID = "request_body_invalid"
REASON_REVOKE_REASON_REQUIRED = "revoke_reason_required"
_STATUS = {REASON_DEVICE_NOT_FOUND: 404}
_RENEWAL_FORBIDDEN = {"device_revoked", "device_signature_invalid"}


def _refusal(state: str, reason: str, status: int) -> JSONResponse:
    return JSONResponse({"state": state, "reason": reason}, status_code=status)


def _registry_refusal(error: DeviceRegistryError) -> JSONResponse:
    return _refusal(STATE_DENIED, error.reason, _STATUS.get(error.reason, 400))


def _serialized(device, *, owner_view: bool, needs_login: bool = False, validity=None,  # noqa: ANN001
                running_jobs: int = 0) -> dict[str, Any]:
    expires = login_expires_at(device.created_at, validity) if validity is not None else None
    live = {**device_live_state(device.id), "running_jobs": running_jobs}
    return serialize_device(device, owner_view=owner_view, live=live, needs_login=needs_login,
                            login_expires_at=expires)


async def _running_jobs(db: AsyncSession, owner_user_id: str) -> dict[str, int]:
    """How many jobs run on each of the owner's devices now (the phone's device status). Only the owner's
    own jobs are counted, as only the owner lists the devices."""
    rows = await db.execute(
        select(DeviceJob.device_id, func.count()).where(
            DeviceJob.owner_user_id == owner_user_id, DeviceJob.status == STATUS_RUNNING,
        ).group_by(DeviceJob.device_id)
    )
    return {device_id: int(count) for device_id, count in rows.all()}


@router.post("/api/v1/devices")
async def register(request: Request, body: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    login = await resolve_gateway_login(db, request.headers)
    if isinstance(login, GatewayRefusal):
        return _refusal(login.state, login.reason, login.http_status)
    user, context = login
    grant = await db.get(OAuthGrant, context.grant_id)
    if grant is None or grant.device_id:
        # A device credential never registers another device; only the user's own login does.
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_LOGIN_REQUIRED, 403)
    try:
        registration = await register_device(
            db, owner_user_id=user.id, client_id=context.oauth_client_id, login_scopes=context.scopes, body=body
        )
    except DeviceRegistryError as error:
        return _registry_refusal(error)
    await db.commit()
    return JSONResponse(
        {
            "state": "registered",
            "device": serialize_device(registration.device, owner_view=True),
            "credential": {
                "refresh_token": registration.refresh_token,
                "client_id": context.oauth_client_id,
                "scopes": list(registration.scopes),
                "audience": DEVICE_AUDIENCE,
            },
        },
        status_code=201,
        headers={"cache-control": "no-store"},
    )


@router.post("/api/v1/devices/self/disable")
async def disable_self(request: Request, db: AsyncSession = Depends(get_db)):
    credential = await resolve_device_credential(db, bearer_token(request.headers))
    if isinstance(credential, str):
        return _refusal(STATE_UNAUTHORIZED, credential, 401)
    await revoke_device(db, credential.device, actor_id=credential.user_id, reason="disabled on the device")
    await db.commit()
    await device_revoked(credential.device.id)
    return {"state": "revoked", "device_id": credential.device.id}


@router.post("/api/v1/devices/self/renew")
async def renew_self(body: Any = Body(None), db: AsyncSession = Depends(get_db)):
    renewal = await renew_device_credential(db, body, now=time.time())
    if isinstance(renewal, str):
        return _refusal(STATE_UNAUTHORIZED, renewal, 403 if renewal in _RENEWAL_FORBIDDEN else 401)
    await db.commit()
    return JSONResponse(
        {
            "state": "renewed",
            "device_id": renewal.device.id,
            "credential": {
                "refresh_token": renewal.refresh_token,
                "client_id": renewal.client_id,
                "scopes": list(renewal.scopes),
                "audience": DEVICE_AUDIENCE,
            },
        },
        headers={"cache-control": "no-store"},
    )


@router.get("/api/v1/devices")
async def my_devices(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    devices = await list_devices(db, owner_user_id=current_user.id)
    needs_login = await devices_needing_login(db, devices)
    validity = await login_validity(db)
    running = await _running_jobs(db, current_user.id)
    return {
        "items": [_serialized(device, owner_view=True, needs_login=device.id in needs_login, validity=validity,
                              running_jobs=running.get(device.id, 0))
                  for device in devices],
        "all_paused": bool(devices) and all(device.paused for device in devices),
    }


@router.patch("/api/v1/devices/{device_id}")
async def update_device(
    device_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body or set(body) - {"name", "folders", "paused"}:
        return _refusal(STATE_DENIED, REASON_BODY_INVALID, 400)
    if "paused" in body and type(body["paused"]) is not bool:
        return _refusal(STATE_DENIED, REASON_BODY_INVALID, 400)
    try:
        device = await owned_device(db, owner_user_id=current_user.id, device_id=device_id)
        if "name" in body:
            await rename_device(db, device, name=body["name"], actor_id=current_user.id)
        if "folders" in body:
            await narrow_folders(db, device, folders=body["folders"], actor_id=current_user.id)
        if "paused" in body:
            await set_paused(db, [device], paused=body["paused"], actor_id=current_user.id)
    except DeviceRegistryError as error:
        return _registry_refusal(error)
    await db.commit()
    if "paused" in body:
        await devices_paused([device], paused=body["paused"])
    return _serialized(device, owner_view=True)


@router.post("/api/v1/devices/{device_id}/revoke")
async def revoke_own_device(
    device_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        device = await owned_device(db, owner_user_id=current_user.id, device_id=device_id)
    except DeviceRegistryError as error:
        return _registry_refusal(error)
    await revoke_device(db, device, actor_id=current_user.id)
    await db.commit()
    await device_revoked(device.id)
    return _serialized(device, owner_view=True)


@router.put("/api/v1/devices/pause")
async def pause_all(
    body: dict[str, Any] = Body(...), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    paused = body.get("paused")
    if type(paused) is not bool:
        return _refusal(STATE_DENIED, REASON_BODY_INVALID, 400)
    devices = await list_devices(db, owner_user_id=current_user.id)
    await set_paused(db, devices, paused=paused, actor_id=current_user.id)
    await db.commit()
    await devices_paused(devices, paused=paused)
    return {"items": [_serialized(device, owner_view=True) for device in devices], "all_paused": paused}


async def _require_admin(db: AsyncSession, user: User) -> JSONResponse | None:
    if not await is_global_admin(db, user.id):
        return _refusal(STATE_DENIED, REASON_ADMIN_REQUIRED, 403)
    return None


@router.get("/api/v1/admin/devices")
async def admin_devices(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if refused := await _require_admin(db, current_user):
        return refused
    devices = await list_devices(db, include_revoked=True)
    owners = {device.owner_user_id: await db.get(User, device.owner_user_id) for device in devices}
    return {"items": [
        {**_serialized(device, owner_view=False),
         "owner_name": getattr(owners.get(device.owner_user_id), "username", None)}
        for device in devices
    ]}


@router.post("/api/v1/admin/devices/{device_id}/revoke")
async def admin_revoke_device(
    device_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if refused := await _require_admin(db, current_user):
        return refused
    reason = str(body.get("reason") or "").strip() if isinstance(body.get("reason"), str) else ""
    if not reason:
        return _refusal(STATE_DENIED, REASON_REVOKE_REASON_REQUIRED, 400)
    device = await db.get(UserDevice, device_id)
    if device is None:
        return _refusal(STATE_DENIED, REASON_DEVICE_NOT_FOUND, 404)
    await revoke_device(db, device, actor_id=current_user.id, reason=reason)
    await db.commit()
    await device_revoked(device.id)
    return _serialized(device, owner_view=False)
