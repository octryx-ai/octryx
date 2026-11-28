"""The claim side of a confirmed takeover: the applicability check and the claim transfer."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItemClaim, WorkItemTakeover
from ...time_utils import utc_now
from .claim_values import DEFAULT_LEASE_SECONDS, RELEASE_EXPIRED, RELEASE_TAKEN_OVER, is_live
from .claims import active_claim
from .takeover_status import CODE_NOT_PENDING, CODE_REQUESTER_NOT_MEMBER, STATUS_CANCELLED, STATUS_PENDING


async def _transfer_claim(db: AsyncSession, takeover: WorkItemTakeover) -> WorkItemClaim | None:
    now = utc_now()
    current = await active_claim(db, takeover.work_item_id)
    if current is not None and takeover.to_agent_hash and current.holder_ref_hash == takeover.to_agent_hash \
            and is_live(current, now):
        return current
    paths: list[str] = []
    if current is not None:
        reason = RELEASE_TAKEN_OVER if is_live(current, now) else RELEASE_EXPIRED
        paths = list(current.paths or [])
        await db.execute(
            update(WorkItemClaim)
            .where(WorkItemClaim.id == current.id, WorkItemClaim.released_at.is_(None))
            .values(released_at=now, release_reason=reason)
            .execution_options(synchronize_session="fetch")
        )
    if not takeover.to_agent_hash:
        return None
    last_epoch = (
        await db.execute(
            select(func.max(WorkItemClaim.epoch)).where(WorkItemClaim.work_item_id == takeover.work_item_id)
        )
    ).scalar_one()
    claim = WorkItemClaim(
        id=str(uuid.uuid4()),
        project_id=takeover.project_id,
        work_item_id=takeover.work_item_id,
        holder_kind=takeover.to_agent_kind or "gateway_session",
        holder_ref_hash=takeover.to_agent_hash,
        holder_user_id=takeover.to_user_id,
        epoch=int(last_epoch or 0) + 1,
        lease_seconds=DEFAULT_LEASE_SECONDS,
        lease_until=now + timedelta(seconds=DEFAULT_LEASE_SECONDS),
        paths=paths,
        claimed_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(claim)
            await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail={"code": "claim_conflict"}) from None
    return claim


async def _cancel(db: AsyncSession, *, ids_of: Any) -> None:
    await db.execute(
        update(WorkItemTakeover).where(ids_of, WorkItemTakeover.status == STATUS_PENDING)
        .values(status=STATUS_CANCELLED).execution_options(synchronize_session="fetch")
    )


async def _require_still_applicable(db: AsyncSession, takeover: WorkItemTakeover, now: Any) -> None:
    current = await active_claim(db, takeover.work_item_id)
    if takeover.from_claim_id:
        stale = current is None or current.id != takeover.from_claim_id
    else:
        stale = current is not None and is_live(current, now)
    if stale:
        await _cancel(db, ids_of=WorkItemTakeover.id == takeover.id)
        raise HTTPException(status_code=409, detail={"code": CODE_NOT_PENDING})
    from ..project.service import get_project_access_details

    members = {str(entry["id"]) for entry in await get_project_access_details(takeover.to_user_id, db)}
    if takeover.project_id not in members:
        raise HTTPException(status_code=409, detail={"code": CODE_REQUESTER_NOT_MEMBER})
