"""Claim fencing of agent writes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkItem, WorkItemClaim
from ...time_utils import utc_now
from ..mcp_work_access import WorkGrantScope, WorkToolHandler, scoped_change_plan, scoped_work_item
from .claim_values import RELEASE_ADMIN, RELEASE_TAKEN_OVER, is_holder
from .claims import held_by, live_claim, lost_to_takeover
from .identity import AgentIdentity, resolve_agent_identity

CODE_CLAIMED_BY_OTHER = "claimed_by_other"
CODE_CLAIM_LOST = "claim_lost"
FENCED_ITEM_TOOLS = frozenset({"work_item_transition", "work_item_note", "change_units_plan", "change_plan_generate"})
FENCED_PLAN_TOOLS = frozenset({"change_plan_decide"})
TRANSITION_TOOL = "work_item_transition"
FENCED_TOOLS = FENCED_ITEM_TOOLS | FENCED_PLAN_TOOLS


def claim_epoch_from(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if type(value) is not int:
        raise HTTPException(status_code=422, detail="claim_epoch must be an integer")
    return value


async def _lost_by_takeover(db: AsyncSession, item: WorkItem, identity: AgentIdentity) -> bool:
    statement = (
        select(WorkItemClaim.release_reason)
        .where(
            WorkItemClaim.work_item_id == item.id,
            WorkItemClaim.holder_kind == identity.kind,
            WorkItemClaim.holder_ref_hash == identity.ref_hash,
        )
        .order_by(WorkItemClaim.claimed_at.desc())
        .limit(1)
    )
    return (await db.execute(statement)).scalar_one_or_none() in (RELEASE_TAKEN_OVER, RELEASE_ADMIN)


async def require_claim_fence(
    db: AsyncSession, *, item: WorkItem, identity: AgentIdentity, claim_epoch: int | None, must_hold: bool = False
) -> WorkItemClaim | None:
    claim = await live_claim(db, item.id)
    if claim is None:
        lost = await lost_to_takeover(db, item.id, kind=identity.kind, ref_hash=identity.ref_hash)
        if claim_epoch is not None or must_hold or lost:  # taken over, nobody claimed since
            raise HTTPException(status_code=409, detail={"code": CODE_CLAIM_LOST})
        return None
    if not is_holder(claim, kind=identity.kind, ref_hash=identity.ref_hash, user_id=identity.user_id):
        lost = claim_epoch is not None or await _lost_by_takeover(db, item, identity)
        code = CODE_CLAIM_LOST if lost else CODE_CLAIMED_BY_OTHER
        raise HTTPException(status_code=409, detail={"code": code, "held_by": await held_by(db, claim)})
    if claim_epoch is not None and claim_epoch != claim.epoch:
        raise HTTPException(status_code=409, detail={"code": CODE_CLAIM_LOST})
    return claim


async def _fenced_item(db: AsyncSession, scope: WorkGrantScope, tool_name: str, arguments: dict) -> WorkItem:
    if tool_name in FENCED_PLAN_TOOLS:
        plan = await scoped_change_plan(db, scope, arguments.get("change_plan_id"))
        item = await db.get(WorkItem, plan.work_item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Change Plan not found")
        return item
    return await scoped_work_item(db, scope, arguments.get("work_item"))


def fenced_handlers(
    handlers: Mapping[str, WorkToolHandler], *, headers: Mapping[str, str] | None = None,
    identity: AgentIdentity | None = None,
) -> dict[str, WorkToolHandler]:
    def wrap(tool_name: str, handler: WorkToolHandler) -> WorkToolHandler:
        async def fenced(db: AsyncSession, *, user: User, scope: WorkGrantScope, arguments: dict[str, Any]):
            epoch = claim_epoch_from(arguments.get("claim_epoch"))
            item = await _fenced_item(db, scope, tool_name, arguments)
            who = identity or await resolve_agent_identity(
                db, user_id=user.id, grant_id=scope.grant_id, headers=headers or {})
            claim = await require_claim_fence(db, item=item, identity=who, claim_epoch=epoch)
            forwarded = {key: value for key, value in arguments.items() if key != "claim_epoch"}
            result = await handler(db, user=user, scope=scope, arguments=forwarded)
            if claim is not None:
                # The item changed under this claim: the Stop hook asks for a handoff update.
                claim.last_write_at = utc_now()
                await db.flush()
            if tool_name == TRANSITION_TOOL:
                from .handoff_memory import capture_if_done

                await capture_if_done(db, item.id)  # a done item keeps its handoff's lessons as knowledge
            return result

        return fenced

    return {name: wrap(name, handler) if name in FENCED_TOOLS else handler for name, handler in handlers.items()}


__all__ = [
    "CODE_CLAIMED_BY_OTHER",
    "CODE_CLAIM_LOST",
    "FENCED_TOOLS",
    "claim_epoch_from",
    "fenced_handlers",
    "require_claim_fence",
]
