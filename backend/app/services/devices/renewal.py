"""Device credential renewal with the device key: a background service never needs a human login."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from ...models.security.oauth_provider import OAuthGrant
from ...time_utils import ensure_utc, utc_now
from .channel_protocol import verify_signature
from .contract import (
    REASON_DEVICE_LOGIN_EXPIRED,
    REASON_DEVICE_NOT_FOUND,
    REASON_DEVICE_REVOKED,
    REASON_LOGIN_REQUIRED,
)
from .credential import device_login_expired, issue_device_grant, revoke_device_grant
from .login_validity import login_validity

RENEWAL_PROTOCOL_VERSION = 1
RENEWAL_WINDOW_SECONDS = 300
REASON_RENEWAL_STALE = "device_renewal_stale"
REASON_RENEWAL_INVALID = "device_renewal_invalid"
REASON_SIGNATURE_INVALID = "device_signature_invalid"
AUDIT_RENEWED = "device.credential.renewed"


@dataclass(frozen=True, slots=True)
class Renewal:
    device: UserDevice
    refresh_token: str
    client_id: str
    scopes: tuple[str, ...]


def renewal_payload(device_id: str, issued_at: int) -> bytes:
    return f"octryx-device-renew:v{RENEWAL_PROTOCOL_VERSION}:{device_id}:{issued_at}".encode()


async def renew_device_credential(db: AsyncSession, body: Any, *, now: float) -> Renewal | str:
    if not isinstance(body, dict):
        return REASON_RENEWAL_INVALID
    device_id, issued_at, signature = body.get("device_id"), body.get("issued_at"), body.get("signature")
    if not isinstance(device_id, str) or not isinstance(signature, str) or type(issued_at) is not int:
        return REASON_RENEWAL_INVALID
    # Row lock: two concurrent renewals (the service and a CLI, two processes) are serialized, so the second sees the
    # first's grant (``device_renewal_stale`` or a clean rotation) and exactly one grant stays live (no-op on SQLite).
    device = await db.get(UserDevice, device_id, with_for_update=True, populate_existing=True) if device_id else None
    if device is None:
        return REASON_DEVICE_NOT_FOUND
    if device.status != DEVICE_STATUS_ACTIVE:
        return REASON_DEVICE_REVOKED
    if not verify_signature(device.public_key, renewal_payload(device.id, issued_at), signature):
        return REASON_SIGNATURE_INVALID
    owner = await db.get(User, device.owner_user_id)
    current = await db.get(OAuthGrant, device.grant_id) if device.grant_id else None
    if owner is None or not owner.is_active or current is None:
        return REASON_LOGIN_REQUIRED
    if device_login_expired(device, await login_validity(db)):
        return REASON_DEVICE_LOGIN_EXPIRED  # the platform's device login validity: ``device enable`` again
    if abs(now - issued_at) > RENEWAL_WINDOW_SECONDS or issued_at <= ensure_utc(current.created_at).timestamp():
        return REASON_RENEWAL_STALE
    was_revoked = current.revoked_at is not None
    await revoke_device_grant(db, current.id)
    grant, refresh_token = await issue_device_grant(
        db, user_id=device.owner_user_id, client_id=current.client_id, device_id=device.id,
        login_scopes=list(current.scopes or []),
    )
    # Never older than the signed request: a used request is then never "newer than the current grant" again.
    grant.created_at = max(utc_now(), datetime.fromtimestamp(issued_at, UTC).replace(tzinfo=None))
    device.grant_id = grant.id
    db.add(AuditLog(user_id=device.owner_user_id, action=AUDIT_RENEWED, resource_type="user_device",
                    resource_id=device.id, details={"previous_grant_revoked": was_revoked}))
    await db.flush()
    return Renewal(device=device, refresh_token=refresh_token, client_id=current.client_id,
                   scopes=tuple(grant.scopes or ()))


__all__ = ["RENEWAL_WINDOW_SECONDS", "Renewal", "renew_device_credential", "renewal_payload"]
