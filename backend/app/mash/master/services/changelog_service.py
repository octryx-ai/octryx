"""MASH changelog service — writes and reads the monotonic change log."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....time_utils import utc_now
from ..models import MashChangeLog


def compute_checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


async def append_change(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_key: str,
    resource_version: str,
    change_type: str,
    payload: dict[str, Any],
) -> MashChangeLog:
    checksum = compute_checksum(payload)
    entry = MashChangeLog(
        resource_type=resource_type,
        resource_key=resource_key,
        resource_version=resource_version,
        change_type=change_type,
        payload=payload,
        checksum=checksum,
        changed_at=utc_now(),
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_changes_since(
    db: AsyncSession,
    *,
    since_sequence: int = 0,
    resource_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    stmt = select(MashChangeLog).where(MashChangeLog.sequence > since_sequence)

    if resource_type and resource_type != "all":
        stmt = stmt.where(MashChangeLog.resource_type == resource_type)

    stmt = stmt.order_by(MashChangeLog.sequence.asc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    changes = rows[:limit]

    serialised = [
        {
            "sequence": c.sequence,
            "resource_type": c.resource_type,
            "resource_key": c.resource_key,
            "resource_version": c.resource_version,
            "change_type": c.change_type,
            "payload": c.payload,
            "checksum": c.checksum,
            "changed_at": c.changed_at.isoformat() if c.changed_at else None,
        }
        for c in changes
    ]

    latest_sequence = changes[-1].sequence if changes else since_sequence

    return {
        "changes": serialised,
        "latest_sequence": latest_sequence,
        "has_more": has_more,
    }
