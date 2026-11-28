"""The device grant: the background credential of a registered device."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE, DEVICE_STATUS_REVOKED
from ...models.security.oauth_provider import OAuthGrant, OAuthRefreshToken
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..data_access import bind_request_viewer
from ..oauth_provider.tokens import hash_token, verify_access_token_for_audiences
from .contract import (
    DEVICE_AUDIENCE,
    DEVICE_GRANT_ABSOLUTE_LIFETIME,
    DEVICE_GRANT_IDLE_TIMEOUT,
    DEVICE_JOB_SCOPES,
    REASON_DEVICE_GRANT_EXPIRED,
    REASON_DEVICE_GRANT_REVOKED,
    REASON_DEVICE_LOGIN_EXPIRED,
    REASON_DEVICE_REVOKED,
    REASON_SCOPE_MISSING,
    REASON_TOKEN_INVALID,
    SCOPE_DEVICE_CONNECT,
)
from .login_validity import login_expires_at, login_validity


@dataclass(frozen=True, slots=True)
class DeviceCredential:
    device: UserDevice
    user_id: str
    grant_id: str


def device_grant_scopes(login_scopes: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({SCOPE_DEVICE_CONNECT} | (set(login_scopes) & DEVICE_JOB_SCOPES))


async def issue_device_grant(
    db: AsyncSession, *, user_id: str, client_id: str, device_id: str, login_scopes: list[str] | tuple[str, ...]
) -> tuple[OAuthGrant, str]:
    scopes = device_grant_scopes(login_scopes)
    grant = OAuthGrant(
        user_id=user_id, client_id=client_id, scopes=scopes, project_ids=None,
        platform_refresh_token_id=None, device_id=device_id,
    )
    db.add(grant)
    await db.flush()
    raw = secrets.token_urlsafe(48)
    db.add(
        OAuthRefreshToken(
            token_hash=hash_token(raw), grant_id=grant.id, client_id=client_id, user_id=user_id,
            scopes=scopes, expires_at=utc_now() + DEVICE_GRANT_IDLE_TIMEOUT,
        )
    )
    await db.flush()
    return grant, raw


async def device_grant_refusal(db: AsyncSession, grant: OAuthGrant) -> str:
    if grant.revoked_at is not None:
        return REASON_DEVICE_GRANT_REVOKED
    if ensure_utc(grant.created_at) + DEVICE_GRANT_ABSOLUTE_LIFETIME <= utc_now_aware():
        return REASON_DEVICE_GRANT_EXPIRED
    device = await db.get(UserDevice, grant.device_id)
    if device is None or device.status != DEVICE_STATUS_ACTIVE or device.owner_user_id != grant.user_id:
        return REASON_DEVICE_REVOKED
    if device_login_expired(device, await login_validity(db)):
        return REASON_DEVICE_LOGIN_EXPIRED
    return ""


def device_login_expired(device: UserDevice, validity) -> bool:  # noqa: ANN001 - a timedelta
    return login_expires_at(device.created_at, validity) <= utc_now_aware()


async def revoke_device_grant(db: AsyncSession, grant_id: str | None) -> None:
    if not grant_id:
        return
    now = utc_now()
    await db.execute(
        update(OAuthGrant).where(OAuthGrant.id == grant_id, OAuthGrant.revoked_at.is_(None)).values(revoked_at=now)
    )
    await db.execute(
        update(OAuthRefreshToken)
        .where(OAuthRefreshToken.grant_id == grant_id, OAuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.flush()


async def revoke_user_device_grants(db: AsyncSession, *, user_id: str) -> int:
    now = utc_now()
    await db.execute(
        update(UserDevice)
        .where(UserDevice.owner_user_id == user_id, UserDevice.status == DEVICE_STATUS_ACTIVE)
        .values(status=DEVICE_STATUS_REVOKED, revoked_at=now, revoked_by=user_id, revoke_reason="credential change")
    )
    grant_ids = (
        await db.execute(
            select(OAuthGrant.id).where(
                OAuthGrant.user_id == user_id, OAuthGrant.device_id.is_not(None), OAuthGrant.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    for grant_id in grant_ids:
        await revoke_device_grant(db, grant_id)
    from ..mobile.devices import revoke_user_phones  # noqa: PLC0415 - paired phones end with the credential too

    await revoke_user_phones(db, user_id=user_id, reason="credential change")
    return len(grant_ids)


async def devices_needing_login(db: AsyncSession, devices: list[UserDevice]) -> set[str]:
    grant_ids = [device.grant_id for device in devices if device.grant_id and device.status == DEVICE_STATUS_ACTIVE]
    grants = {
        grant.id: grant
        for grant in (await db.execute(select(OAuthGrant).where(OAuthGrant.id.in_(grant_ids)))).scalars()
    } if grant_ids else {}
    expired_before = utc_now_aware() - DEVICE_GRANT_ABSOLUTE_LIFETIME
    validity = await login_validity(db)
    return {
        device.id for device in devices
        if device.status == DEVICE_STATUS_ACTIVE and (
            (grant := grants.get(device.grant_id or "")) is None
            or grant.revoked_at is not None or ensure_utc(grant.created_at) <= expired_before
            or device_login_expired(device, validity)
        )
    }


async def resolve_device_credential(db: AsyncSession, token: str) -> DeviceCredential | str:
    claims = verify_access_token_for_audiences(token, audiences={DEVICE_AUDIENCE}) if token else None
    if claims is None:
        return REASON_TOKEN_INVALID
    if SCOPE_DEVICE_CONNECT not in str(claims.get("scope") or "").split():
        return REASON_SCOPE_MISSING
    grant = await db.get(OAuthGrant, str(claims.get("grant_id") or ""))
    if grant is None or not grant.device_id or grant.user_id != str(claims.get("sub") or ""):
        return REASON_TOKEN_INVALID
    refusal = await device_grant_refusal(db, grant)
    if refusal:
        return refusal
    device = await db.get(UserDevice, grant.device_id)
    bind_request_viewer(grant.user_id)
    return DeviceCredential(device=device, user_id=grant.user_id, grant_id=grant.id)


__all__ = [
    "DeviceCredential",
    "device_grant_refusal",
    "device_login_expired",
    "device_grant_scopes",
    "devices_needing_login",
    "issue_device_grant",
    "revoke_device_grant",
    "resolve_device_credential",
    "revoke_user_device_grants",
]
