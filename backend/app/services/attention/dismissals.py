"""Dismissing a finished entry ("Done"): an audit row per person and key, no new table."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User
from ...time_utils import utc_now

AUDIT_ACTION = "attention.dismissed"
DISMISSIBLE_PREFIXES = ("done:", "live:", "turn:")
KEEP_FOR = timedelta(days=7)


def dismissible(key: str) -> bool:
    return isinstance(key, str) and 0 < len(key) <= 120 and key.startswith(DISMISSIBLE_PREFIXES)


async def dismissed_keys(db: AsyncSession, user: User) -> set[str]:
    rows = (await db.execute(select(AuditLog.resource_id).where(
        AuditLog.user_id == user.id, AuditLog.action == AUDIT_ACTION,
        AuditLog.created_at >= (utc_now() - KEEP_FOR).replace(tzinfo=None),
    ))).scalars().all()
    return {str(row) for row in rows if row}


async def dismiss(db: AsyncSession, user: User, key: str) -> None:
    db.add(AuditLog(user_id=user.id, action=AUDIT_ACTION, resource_type="attention_item", resource_id=key,
                    details={"key": key}))
    await db.flush()


__all__ = ["AUDIT_ACTION", "dismiss", "dismissed_keys", "dismissible"]
