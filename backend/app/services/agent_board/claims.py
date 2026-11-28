"""Work-item claims: one active agent holder per Work Item, with a lease and a fencing epoch."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, WorkItem, WorkItemClaim
from ...time_utils import utc_now
from .claim_listing import _display_names
from .claim_values import (
    ADMIN_RELEASE_AUDIT_ACTION,
    DEFAULT_LEASE_SECONDS,
    KIND_GATEWAY_SESSION,
    RELEASE_ADMIN,
    RELEASE_EXPIRED,
    RELEASE_RELEASED,
    RELEASE_TAKEN_OVER,
    is_holder,
    is_live,
    iso,
)


async def active_claim(db: AsyncSession, work_item_id: str) -> WorkItemClaim | None:
    statement = select(WorkItemClaim).where(
        WorkItemClaim.work_item_id == work_item_id, WorkItemClaim.released_at.is_(None)
    )
    return (await db.execute(statement)).scalar_one_or_none()


async def live_claim(db: AsyncSession, work_item_id: str) -> WorkItemClaim | None:
    claim = await active_claim(db, work_item_id)
    return claim if claim is not None and is_live(claim, utc_now()) else None


async def lost_to_takeover(db: AsyncSession, work_item_id: str, *, kind: str, ref_hash: str) -> bool:
    latest = (
        await db.execute(
            select(WorkItemClaim).where(WorkItemClaim.work_item_id == work_item_id)
            .order_by(WorkItemClaim.claimed_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return (latest is not None and latest.holder_kind == kind and latest.holder_ref_hash == ref_hash
            and latest.release_reason == RELEASE_TAKEN_OVER)


async def held_by(db: AsyncSession, claim: WorkItemClaim) -> dict[str, Any]:
    names = await _display_names(db, [claim.holder_user_id])
    return {
        "user": {"id": claim.holder_user_id, "display_name": names.get(claim.holder_user_id)},
        "agent_hash": claim.holder_ref_hash,
        "since": iso(claim.claimed_at),
        "lease_until": iso(claim.lease_until),
        "paths": list(claim.paths or []),
    }


def _claimed(claim: WorkItemClaim) -> dict[str, Any]:
    return {"claimed": True, "claim_id": claim.id, "epoch": claim.epoch, "lease_until": iso(claim.lease_until)}


async def claim_work_item(
    db: AsyncSession, *, item: WorkItem, kind: str, ref_hash: str, user_id: str,
    paths: list[str] | None, lease_seconds: int,
) -> dict[str, Any]:
    now = utc_now()
    current = await active_claim(db, item.id)
    if current is not None and is_live(current, now):
        if not is_holder(current, kind=kind, ref_hash=ref_hash, user_id=user_id):
            return {"claimed": False, "held_by": await held_by(db, current)}
        current.lease_seconds = lease_seconds
        current.lease_until = now + timedelta(seconds=lease_seconds)
        if paths is not None:
            current.paths = paths
        await db.flush()
        return _claimed(current)
    if current is None and await lost_to_takeover(db, item.id, kind=kind, ref_hash=ref_hash):
        # The item was taken over from this identity: it cannot simply claim it back.
        return {"claimed": False, "code": "claim_lost", "held_by": None}
    if current is not None:
        await db.execute(
            update(WorkItemClaim)
            .where(WorkItemClaim.id == current.id, WorkItemClaim.released_at.is_(None))
            .values(released_at=now, release_reason=RELEASE_EXPIRED)
            .execution_options(synchronize_session="fetch")
        )
    last_epoch = (
        await db.execute(select(func.max(WorkItemClaim.epoch)).where(WorkItemClaim.work_item_id == item.id))
    ).scalar_one()
    claim = WorkItemClaim(
        id=str(uuid.uuid4()),
        project_id=item.project_id,
        work_item_id=item.id,
        holder_kind=kind,
        holder_ref_hash=ref_hash,
        holder_user_id=user_id,
        epoch=int(last_epoch or 0) + 1,
        lease_seconds=lease_seconds,
        lease_until=now + timedelta(seconds=lease_seconds),
        paths=paths or [],
        claimed_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(claim)
            await db.flush()
    except IntegrityError:
        # Another holder inserted between the read and this insert: exactly one wins.
        winner = await active_claim(db, item.id)
        if winner is None:
            raise HTTPException(status_code=409, detail="Work item claim conflict; retry") from None
        return {"claimed": False, "held_by": await held_by(db, winner)}
    return _claimed(claim)


async def release_own_claim(db: AsyncSession, *, item: WorkItem, kind: str, ref_hash: str, user_id: str) -> dict:
    current = await active_claim(db, item.id)
    if current is None or not is_holder(current, kind=kind, ref_hash=ref_hash, user_id=user_id):
        return {"released": False}
    current.released_at = utc_now()
    current.release_reason = RELEASE_RELEASED
    await db.flush()
    return {"released": True, "claim_id": current.id}


async def renew_gateway_claims(db: AsyncSession, ref_hash: str, now: datetime) -> None:
    rows = (
        await db.execute(
            select(WorkItemClaim).where(
                WorkItemClaim.holder_kind == KIND_GATEWAY_SESSION,
                WorkItemClaim.holder_ref_hash == ref_hash,
                WorkItemClaim.released_at.is_(None),
                WorkItemClaim.lease_until > now,
            )
        )
    ).scalars().all()
    for claim in rows:
        claim.lease_until = now + timedelta(seconds=claim.lease_seconds or DEFAULT_LEASE_SECONDS)


async def release_holder_claims(db: AsyncSession, *, kind: str, ref_hash: str, reason: str) -> int:
    rows = (
        await db.execute(
            select(WorkItemClaim).where(
                WorkItemClaim.holder_kind == kind,
                WorkItemClaim.holder_ref_hash == ref_hash,
                WorkItemClaim.released_at.is_(None),
            )
        )
    ).scalars().all()
    now = utc_now()
    for claim in rows:
        claim.released_at = now
        claim.release_reason = reason
    await db.flush()
    return len(rows)


async def admin_release_claim(db: AsyncSession, *, claim: WorkItemClaim, actor_user_id: str) -> dict[str, Any]:
    if claim.released_at is None:
        claim.released_at = utc_now()
        claim.release_reason = RELEASE_ADMIN
        db.add(
            AuditLog(
                user_id=actor_user_id,
                action=ADMIN_RELEASE_AUDIT_ACTION,
                resource_type="work_item_claim",
                resource_id=claim.id,
                project_id=claim.project_id,
                details={"project_id": claim.project_id, "work_item_id": claim.work_item_id,
                         "holder_user_id": claim.holder_user_id, "agent_hash": claim.holder_ref_hash,
                         "epoch": claim.epoch},
            )
        )
        await db.flush()
    return {"id": claim.id, "released_at": iso(claim.released_at), "release_reason": claim.release_reason}


__all__ = [
    "active_claim",
    "admin_release_claim",
    "claim_work_item",
    "held_by",
    "lost_to_takeover",
    "live_claim",
    "release_holder_claims",
    "release_own_claim",
    "renew_gateway_claims",
]
