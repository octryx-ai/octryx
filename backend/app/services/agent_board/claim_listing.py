"""Claim listings for the UI and Work Item lookup by id or source key."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkItem, WorkItemClaim
from ...time_utils import utc_now
from .claim_values import LIST_LIMIT, iso


async def _display_names(db: AsyncSession, user_ids: Iterable[str]) -> dict[str, str]:
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(ids)))).all()
    return {user_id: display_name or username for user_id, display_name, username in rows}


async def list_live_claims(db: AsyncSession, project_ids: Iterable[str]) -> list[dict[str, Any]]:
    ids = sorted(set(project_ids))
    if not ids:
        return []
    rows = (
        await db.execute(
            select(WorkItemClaim, WorkItem.source_key, WorkItem.title)
            .join(WorkItem, WorkItem.id == WorkItemClaim.work_item_id)
            .where(
                WorkItemClaim.project_id.in_(ids),
                WorkItemClaim.released_at.is_(None),
                WorkItemClaim.lease_until > utc_now(),
            )
            .order_by(WorkItemClaim.claimed_at.desc())
            .limit(LIST_LIMIT)
        )
    ).all()
    names = await _display_names(db, [claim.holder_user_id for claim, _, _ in rows])
    return [
        {
            "id": claim.id,
            "project_id": claim.project_id,
            "work_item": {"id": claim.work_item_id, "key": key, "title": title},
            "holder": {
                "user": {"id": claim.holder_user_id, "display_name": names.get(claim.holder_user_id)},
                "agent_hash": claim.holder_ref_hash,
                "kind": claim.holder_kind,
            },
            "epoch": claim.epoch,
            "lease_until": iso(claim.lease_until),
            "paths": list(claim.paths or []),
            "claimed_at": iso(claim.claimed_at),
        }
        for claim, key, title in rows
    ]


def matches_query(query: str, *values: str | None) -> bool:
    needle = query.strip().lower()
    return bool(needle) and any(needle in (value or "").lower() for value in values)


async def work_item_rows(db: AsyncSession, project_ids: Iterable[str], keys: Iterable[str]) -> dict[str, WorkItem]:
    wanted, ids = sorted(set(keys)), sorted(set(project_ids))
    if not wanted or not ids:
        return {}
    rows = (
        await db.execute(
            select(WorkItem).where(
                WorkItem.project_id.in_(ids), or_(WorkItem.id.in_(wanted), WorkItem.source_key.in_(wanted))
            )
        )
    ).scalars().all()
    found: dict[str, WorkItem] = {}
    for row in rows:
        found.setdefault(row.id, row)
        if row.source_key:
            found.setdefault(row.source_key, row)
    return found
