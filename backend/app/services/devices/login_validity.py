"""How long a device login stays valid: one platform setting for paired phones and Macs.

``system_config`` key ``devices.login_validity``, written as ``<n>h`` or ``<n>d`` (``12h``, ``1d``, ``90d``).
Bounds: at least one hour, at most 365 days. "Never expires" does not exist. Without a stored value it is 90 days.

The validity counts from when the device was registered (a Mac: ``device enable``; a phone: its pairing). It is
read on every check, so shortening it takes effect at once for every device. After it, a Mac's credential can
no longer mint or renew tokens (``device enable`` again) and a phone must be paired again.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig
from ...time_utils import ensure_utc

CONFIG_KEY = "devices.login_validity"
AUDIT_ACTION = "admin.devices.login_validity"
DEFAULT_VALIDITY = "90d"
MIN_VALIDITY = timedelta(hours=1)
MAX_VALIDITY = timedelta(days=365)
REASON_VALIDITY_INVALID = "device_login_validity_invalid"
_PATTERN = re.compile(r"^([1-9][0-9]{0,4})([hd])$")


def parse_validity(text: object) -> timedelta | None:
    """``timedelta`` for ``<n>h`` / ``<n>d`` within the bounds, else ``None``."""
    match = _PATTERN.match(str(text or "").strip().lower())
    if match is None:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    value = timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
    return value if MIN_VALIDITY <= value <= MAX_VALIDITY else None


async def _stored(db: AsyncSession) -> SystemConfig | None:
    return (await db.execute(select(SystemConfig).where(SystemConfig.key == CONFIG_KEY))).scalar_one_or_none()


async def login_validity_text(db: AsyncSession) -> str:
    row = await _stored(db)
    value = str(row.value or "").strip().lower() if row is not None else ""
    return value if parse_validity(value) is not None else DEFAULT_VALIDITY


async def login_validity(db: AsyncSession) -> timedelta:
    validity = parse_validity(await login_validity_text(db))
    assert validity is not None  # the default parses
    return validity


def login_expires_at(created_at: datetime, validity: timedelta) -> datetime:
    return ensure_utc(created_at) + validity


async def set_login_validity(db: AsyncSession, *, value: object, actor_id: str) -> str:
    """Store a new validity (audited) and return it normalized; raises ``ValueError`` (fixed reason) otherwise."""
    if parse_validity(value) is None:
        raise ValueError(REASON_VALIDITY_INVALID)
    normalized = str(value).strip().lower()
    row = await _stored(db)
    previous = str(row.value or "") if row is not None else ""
    if row is None:
        row = SystemConfig(key=CONFIG_KEY, description="How long a device login (phone or Mac) stays valid")
        db.add(row)
    row.value = normalized
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="system_config", resource_id=CONFIG_KEY,
                    details={"value": normalized, "previous": previous or DEFAULT_VALIDITY}))
    await db.flush()
    return normalized


__all__ = [
    "CONFIG_KEY",
    "DEFAULT_VALIDITY",
    "MAX_VALIDITY",
    "MIN_VALIDITY",
    "REASON_VALIDITY_INVALID",
    "login_expires_at",
    "login_validity",
    "login_validity_text",
    "parse_validity",
    "set_login_validity",
]
