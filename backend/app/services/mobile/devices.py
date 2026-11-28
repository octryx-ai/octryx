"""A user's paired phones: resolving the phone's credential, listing, revoking."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.touch import touch_if_stale
from ...models import AuditLog, MobileDevice, User
from ...models.security.mobile import MOBILE_ACTIVE, MOBILE_REVOKED
from ...models.security.oauth_provider import OAuthGrant
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..data_access import bind_request_viewer
from ..devices.login_validity import login_expires_at, login_validity
from ..oauth_provider.flows import _login_session_alive
from .contract import AUDIT_DEVICE_REVOKED, REASON_LOGIN_EXPIRED, REASON_NOT_FOUND, REASON_NOT_PAIRED, REASON_REVOKED
from .pairing import secret_hash


async def phone_refusal(db: AsyncSession, device: MobileDevice | None, *, validity: timedelta | None = None) -> str:
    if device is None:
        return REASON_NOT_PAIRED
    if device.status != MOBILE_ACTIVE:
        return REASON_REVOKED
    owner = await db.get(User, device.owner_user_id)
    if owner is None or not owner.is_active:
        return REASON_REVOKED
    # The octryx-claude login the phone was paired from: revoking it (logout, admin, credential change) ends the phone.
    grant = await db.get(OAuthGrant, device.grant_id) if device.grant_id else None
    if grant is None or grant.revoked_at is not None or grant.user_id != device.owner_user_id:
        return REASON_REVOKED
    # ... and the web login that login is tied to: signing out of the platform (or its expiry) ends the phone too.
    if not await _login_session_alive(db, grant.platform_refresh_token_id):
        return REASON_LOGIN_EXPIRED
    if login_expires_at(device.created_at, validity or await login_validity(db)) <= utc_now_aware():
        return REASON_LOGIN_EXPIRED
    return ""


async def resolve_phone(db: AsyncSession, secret: str) -> MobileDevice | str:
    if not isinstance(secret, str) or not 20 <= len(secret) <= 128:
        return REASON_NOT_PAIRED
    device = (
        await db.execute(select(MobileDevice).where(MobileDevice.secret_hash == secret_hash(secret)))
    ).scalar_one_or_none()
    refusal = await phone_refusal(db, device)
    if refusal:
        return refusal
    assert device is not None
    await touch_if_stale(db, MobileDevice, device.id, device.last_seen_at, column="last_seen_at")
    bind_request_viewer(device.owner_user_id)
    return device


async def list_phones(db: AsyncSession, *, owner_user_id: str) -> list[MobileDevice]:
    rows = await db.execute(
        select(MobileDevice)
        .where(MobileDevice.owner_user_id == owner_user_id, MobileDevice.status == MOBILE_ACTIVE)
        .order_by(MobileDevice.created_at.desc())
    )
    return list(rows.scalars().all())


async def owned_phone(db: AsyncSession, *, owner_user_id: str, device_id: str) -> MobileDevice | str:
    device = await db.get(MobileDevice, device_id) if device_id else None
    if device is None or device.owner_user_id != owner_user_id:
        return REASON_NOT_FOUND
    return device


async def revoke_phone(db: AsyncSession, device: MobileDevice, *, actor_id: str, reason: str) -> None:
    if device.status == MOBILE_REVOKED:
        return
    device.status, device.revoked_at = MOBILE_REVOKED, utc_now()
    device.revoked_by, device.revoke_reason = actor_id, reason[:200]
    db.add(AuditLog(user_id=device.owner_user_id, action=AUDIT_DEVICE_REVOKED, resource_type="mobile_device",
                    resource_id=device.id, details={"reason": reason[:200], "actor_user_id": actor_id}))
    await db.flush()


async def revoke_user_phones(db: AsyncSession, *, user_id: str, reason: str) -> None:
    await db.execute(
        update(MobileDevice)
        .where(MobileDevice.owner_user_id == user_id, MobileDevice.status == MOBILE_ACTIVE)
        .values(status=MOBILE_REVOKED, revoked_at=utc_now(), revoked_by=user_id, revoke_reason=reason[:200])
    )
    await db.flush()


def serialize_phone(device: MobileDevice, *, validity: timedelta, current_id: str = "") -> dict[str, Any]:
    expires = login_expires_at(device.created_at, validity)
    return {
        "id": device.id,
        "name": device.name,
        "kind": "phone",
        "status": device.status,
        "created_at": ensure_utc(device.created_at).isoformat(),
        "last_seen_at": ensure_utc(device.last_seen_at).isoformat() if device.last_seen_at else None,
        "login_expires_at": expires.isoformat(),
        "expired": expires <= utc_now_aware(),
        "this_device": bool(current_id) and device.id == current_id,
    }


__all__ = [
    "list_phones",
    "owned_phone",
    "phone_refusal",
    "resolve_phone",
    "revoke_phone",
    "revoke_user_phones",
    "serialize_phone",
]
