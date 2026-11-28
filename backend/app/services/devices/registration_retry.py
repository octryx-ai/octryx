"""``device enable`` retried after a lost answer: the server can have registered the device while the launcher timed out
(``platform_unreachable``), so its retry meets its own entry as ``device_name_taken``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from .credential import issue_device_grant, revoke_device_grant

AUDIT_REGISTRATION_RETRIED = "device.registration_retried"
REGISTRATION_PROTOCOL_VERSION = 1


def registration_payload(name: str, public_key: str) -> bytes:
    return f"octryx-device-register:v{REGISTRATION_PROTOCOL_VERSION}:{name.lower()}:{public_key}".encode()


async def own_retry(
    db: AsyncSession, *, owner_user_id: str, name: str, public_key: str, key_proof: Any
) -> UserDevice | None:
    if not isinstance(key_proof, str) or not key_proof:
        return None
    device = (
        await db.execute(
            select(UserDevice).where(
                UserDevice.owner_user_id == owner_user_id,
                UserDevice.name_key == name.lower(),
                UserDevice.status == DEVICE_STATUS_ACTIVE,
            )
        )
    ).scalars().first()
    if device is None or device.public_key != public_key:
        return None
    from .channel_protocol import verify_signature  # channel imports the registry: imported here, not at module load

    return device if verify_signature(public_key, registration_payload(name, public_key), key_proof) else None


async def reissue(
    db: AsyncSession, device: UserDevice, *, owner_user_id: str, client_id: str, login_scopes: Iterable[str],
    fields: Mapping[str, Any],
) -> tuple[Any, str]:
    for key, value in fields.items():
        setattr(device, key, value)
    await revoke_device_grant(db, device.grant_id)
    grant, refresh_token = await issue_device_grant(
        db, user_id=owner_user_id, client_id=client_id, device_id=device.id, login_scopes=list(login_scopes)
    )
    device.grant_id = grant.id
    await db.flush()
    return grant, refresh_token
