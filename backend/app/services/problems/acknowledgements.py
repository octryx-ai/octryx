"""Acknowledging a problem: hidden for that person until it occurs again, an audit row, no new table."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User
from ...time_utils import ensure_utc, utc_now
from .model import Problem, iso

AUDIT_ACTION = "problems.acknowledged"
KEEP_FOR = timedelta(days=30)
MAX_KEY_LENGTH = 200


async def acknowledged(db: AsyncSession, user: User) -> dict[str, datetime | None]:
    rows = (await db.execute(
        select(AuditLog.resource_id, AuditLog.details)
        .where(AuditLog.user_id == user.id, AuditLog.action == AUDIT_ACTION,
               AuditLog.created_at >= utc_now() - KEEP_FOR)
        .order_by(AuditLog.created_at.asc())
    )).all()
    result: dict[str, datetime | None] = {}
    for key, details in rows:
        raw = (details or {}).get("since") if isinstance(details, dict) else None
        result[str(key)] = datetime.fromisoformat(raw) if raw else None
    return result


def is_hidden(problem: Problem, acks: dict[str, datetime | None]) -> bool:
    if problem.key not in acks:
        return False
    acked_since = acks[problem.key]
    if problem.since is None or acked_since is None:
        return True
    return ensure_utc(problem.since) <= ensure_utc(acked_since)


async def acknowledge(db: AsyncSession, user: User, problem: Problem) -> None:
    db.add(AuditLog(user_id=user.id, action=AUDIT_ACTION, resource_type="problem", resource_id=problem.key,
                    details={"key": problem.key, "kind": problem.kind, "since": iso(problem.since)}))
    await db.flush()


__all__ = ["AUDIT_ACTION", "MAX_KEY_LENGTH", "acknowledge", "acknowledged", "is_hidden"]
