"""Device registration, rename, revoke, pause and folder narrowing.

Owner rules are hard invariants here, not policy: only the owner registers, renames, narrows, pauses or
revokes a device through the user routes; a platform admin can only revoke (with a reason) through the admin
route. The platform can never widen a device's folders or profiles: those come from the device itself
(``report_device_state`` on the channel ``hello``) and the platform may only remove folders.

Every change writes an ``AuditLog`` row (``device.*``) and flushes; the caller commits.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE, DEVICE_STATUS_REVOKED
from ...time_utils import utc_now
from . import registration_retry
from .contract import (
    OS_VALUES,
    REASON_DEVICE_NAME_TAKEN,
    REASON_DEVICE_NOT_FOUND,
    REASON_DEVICE_OS_INVALID,
    REASON_DEVICE_REVOKED,
    REASON_FOLDERS_WIDENING,
)
from .credential import device_login_expired, issue_device_grant, revoke_device_grant
from .login_validity import login_validity
from .registry_values import (
    SERVICE_KINDS,
    DeviceRegistryError,
    _public_key,
    _short_text,
    normalize_folders,
    normalize_name,
    normalize_parallel_jobs,
    normalize_profiles,
)

AUDIT_REGISTERED = "device.registered"
AUDIT_RENAMED = "device.renamed"
AUDIT_REVOKED = "device.revoked"
AUDIT_PAUSED = "device.paused"
AUDIT_RESUMED = "device.resumed"
AUDIT_FOLDERS_NARROWED = "device.folders_narrowed"
MAX_REASON_CHARS = 200


@dataclass(frozen=True, slots=True)
class Registration:
    device: UserDevice
    refresh_token: str
    scopes: tuple[str, ...]


def _audit(db: AsyncSession, *, actor_id: str, action: str, device: UserDevice, details: dict[str, Any]) -> None:
    db.add(AuditLog(user_id=actor_id, action=action, resource_type="user_device", resource_id=device.id,
                    details={"owner_user_id": device.owner_user_id, **details}))


async def _name_taken(db: AsyncSession, owner_user_id: str, name: str, *, except_id: str = "") -> bool:
    row = (
        await db.execute(
            select(UserDevice.id).where(
                UserDevice.owner_user_id == owner_user_id,
                UserDevice.name_key == name.lower(),
                UserDevice.status == DEVICE_STATUS_ACTIVE,
                UserDevice.id != except_id,
            )
        )
    ).first()
    return row is not None


async def _retire_expired_namesake(db: AsyncSession, owner_user_id: str, name: str) -> None:
    """``device enable`` after the device login validity ended: the expired registration of the same name makes
    room for the new one (revoked, audited), so the person is never locked out of their own device name."""
    rows = (
        await db.execute(
            select(UserDevice).where(
                UserDevice.owner_user_id == owner_user_id,
                UserDevice.name_key == name.lower(),
                UserDevice.status == DEVICE_STATUS_ACTIVE,
            )
        )
    ).scalars().all()
    validity = await login_validity(db)
    for device in rows:
        if not device_login_expired(device, validity):
            continue
        device.status, device.revoked_at = DEVICE_STATUS_REVOKED, utc_now()
        device.revoked_by, device.revoke_reason = owner_user_id, "device login expired"
        await revoke_device_grant(db, device.grant_id)
        _audit(db, actor_id=owner_user_id, action="device.login_expired.replaced", device=device, details={})
    await db.flush()


async def register_device(
    db: AsyncSession, *, owner_user_id: str, client_id: str, login_scopes: Iterable[str], body: Mapping[str, Any]
) -> Registration:
    """A new device of ``owner_user_id`` and its device credential. Raises ``DeviceRegistryError``."""
    name = normalize_name(body.get("name"))
    os_name = _short_text(body.get("os"), OS_VALUES)
    if os_name is None:
        raise DeviceRegistryError(REASON_DEVICE_OS_INVALID)
    public_key = _public_key(body.get("public_key"))
    folders = normalize_folders(body.get("folders", []))
    profiles = normalize_profiles(body.get("profiles_available", ["governed"]))
    parallel = normalize_parallel_jobs(body.get("max_parallel_jobs"))
    await _retire_expired_namesake(db, owner_user_id, name)
    fields = {"os": os_name, "client_version": _short_text(body.get("client_version")),
              "service_kind": _short_text(body.get("service_kind"), SERVICE_KINDS),
              "folders": folders, "profiles": profiles, "max_parallel_jobs": parallel}
    if await _name_taken(db, owner_user_id, name):
        retried = await registration_retry.own_retry(db, owner_user_id=owner_user_id, name=name,
                                                     public_key=public_key, key_proof=body.get("key_proof"))
        if retried is None:
            raise DeviceRegistryError(REASON_DEVICE_NAME_TAKEN)
        grant, refresh_token = await registration_retry.reissue(
            db, retried, owner_user_id=owner_user_id, client_id=client_id, login_scopes=login_scopes, fields=fields)
        _audit(db, actor_id=owner_user_id, action=registration_retry.AUDIT_REGISTRATION_RETRIED, device=retried,
               details={"name": name, "folder_count": len(folders)})
        await db.flush()
        return Registration(device=retried, refresh_token=refresh_token, scopes=tuple(grant.scopes or ()))
    device = UserDevice(owner_user_id=owner_user_id, name=name, name_key=name.lower(), public_key=public_key,
                        **fields)
    db.add(device)
    await db.flush()
    grant, refresh_token = await issue_device_grant(
        db, user_id=owner_user_id, client_id=client_id, device_id=device.id, login_scopes=list(login_scopes)
    )
    device.grant_id = grant.id
    _audit(db, actor_id=owner_user_id, action=AUDIT_REGISTERED, device=device,
           details={"name": name, "os": os_name, "profiles": profiles, "folder_count": len(folders)})
    await db.flush()
    return Registration(device=device, refresh_token=refresh_token, scopes=tuple(grant.scopes or ()))


async def owned_device(db: AsyncSession, *, owner_user_id: str, device_id: str) -> UserDevice:
    """The caller's own device; another user's device is the same ``device_not_found`` as a missing one."""
    device = await db.get(UserDevice, device_id) if device_id else None
    if device is None or device.owner_user_id != owner_user_id:
        raise DeviceRegistryError(REASON_DEVICE_NOT_FOUND)
    return device


def _require_active(device: UserDevice) -> None:
    if device.status != DEVICE_STATUS_ACTIVE:
        raise DeviceRegistryError(REASON_DEVICE_REVOKED)


async def rename_device(db: AsyncSession, device: UserDevice, *, name: Any, actor_id: str) -> None:
    _require_active(device)
    new_name = normalize_name(name)
    if new_name == device.name:
        return
    if await _name_taken(db, device.owner_user_id, new_name, except_id=device.id):
        raise DeviceRegistryError(REASON_DEVICE_NAME_TAKEN)
    _audit(db, actor_id=actor_id, action=AUDIT_RENAMED, device=device, details={"from": device.name, "to": new_name})
    device.name, device.name_key = new_name, new_name.lower()
    await db.flush()


async def narrow_folders(db: AsyncSession, device: UserDevice, *, folders: Any, actor_id: str) -> list[str]:
    """The platform may only remove folders; a folder not already allowed is ``device_folders_platform_cannot_add``."""
    _require_active(device)
    requested = normalize_folders(folders)
    current = list(device.folders or [])
    if any(folder not in current for folder in requested):
        raise DeviceRegistryError(REASON_FOLDERS_WIDENING)
    removed = [folder for folder in current if folder not in requested]
    if removed:
        device.folders = [folder for folder in current if folder in requested]
        _audit(db, actor_id=actor_id, action=AUDIT_FOLDERS_NARROWED, device=device,
               details={"removed_count": len(removed), "folder_count": len(device.folders)})
        await db.flush()
    return removed


async def set_paused(db: AsyncSession, devices: Iterable[UserDevice], *, paused: bool, actor_id: str) -> int:
    changed = 0
    for device in devices:
        if device.status != DEVICE_STATUS_ACTIVE or bool(device.paused) == paused:
            continue
        device.paused = paused
        _audit(db, actor_id=actor_id, action=AUDIT_PAUSED if paused else AUDIT_RESUMED, device=device, details={})
        changed += 1
    await db.flush()
    return changed


async def revoke_device(db: AsyncSession, device: UserDevice, *, actor_id: str, reason: str = "") -> bool:
    """Revoke the device and its credential at once; ``False`` when it already was revoked."""
    if device.status == DEVICE_STATUS_REVOKED:
        return False
    device.status = DEVICE_STATUS_REVOKED
    device.revoked_at = utc_now()
    device.revoked_by = actor_id
    device.revoke_reason = str(reason or "")[:MAX_REASON_CHARS] or None
    await revoke_device_grant(db, device.grant_id)
    _audit(db, actor_id=actor_id, action=AUDIT_REVOKED, device=device,
           details={"by_owner": actor_id == device.owner_user_id, "reason": device.revoke_reason})
    await db.flush()
    return True


async def report_device_state(db: AsyncSession, device: UserDevice, report: Mapping[str, Any]) -> None:
    """The device's own report (channel ``hello``): its folders, profiles, parallel limit and versions.

    Invalid values keep the stored ones; the device is the only source that may widen its folders.
    """
    for key, normalize, attribute in (
        ("folders", normalize_folders, "folders"),
        ("profiles_available", normalize_profiles, "profiles"),
        ("max_parallel_jobs", normalize_parallel_jobs, "max_parallel_jobs"),
    ):
        if key in report:
            try:
                setattr(device, attribute, normalize(report[key]))
            except DeviceRegistryError:
                continue
    version = _short_text(report.get("client_version"))
    if version:
        device.client_version = version
    service_kind = _short_text(report.get("service_kind"), SERVICE_KINDS)
    if service_kind:
        device.service_kind = service_kind
    device.last_seen_at = utc_now()
    await db.flush()


async def list_devices(db: AsyncSession, *, owner_user_id: str | None = None, include_revoked: bool = False):
    query = select(UserDevice).order_by(func.lower(UserDevice.name))
    if owner_user_id is not None:
        query = query.where(UserDevice.owner_user_id == owner_user_id)
    if not include_revoked:
        query = query.where(UserDevice.status == DEVICE_STATUS_ACTIVE)
    return list((await db.execute(query)).scalars().all())


__all__ = [
    "Registration",
    "list_devices",
    "narrow_folders",
    "owned_device",
    "register_device",
    "rename_device",
    "report_device_state",
    "revoke_device",
    "set_paused",
]
