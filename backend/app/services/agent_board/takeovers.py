"""Takeovers: move a Work Item's claim to another agent, confirmed only by a person in the UI.

- **Request** (:func:`request_takeover`): a member's agent asks for an item someone else holds, or an admin asks
  a person to take an item over (``handoff-requests``). One ``pending`` takeover per item and requester; asking
  again answers the pending one. It posts a linked ``handoff_request`` board message. It is ``automatic`` when the
  held claim already has an automatic handoff request.
- **Decision** (:func:`decide_takeover`): only the receiving user (``to_user``), a Workspace admin/owner or a
  platform admin; never an agent (there is no MCP tool for it). The status moves ``pending`` → ``confirmed`` /
  ``declined`` by compare-and-set, so a racing confirm and decline have exactly one winner; anything else is
  409 ``takeover_not_pending``. A pending takeover past ``expires_at`` reads, and is stored as, ``expired``.
- **Confirm** transfers the claim in the same transaction: the live claim is released ``taken_over`` and the
  requester's agent gets a new claim with the next epoch and a fresh lease (an admin request without an agent
  only releases it; the person's agent claims next). The old holder's later writes are fenced (``claim_lost``).
  It posts ``handoff_accept``, audits both users and answers with the latest handoff.

States and codes live in ``takeover_status``, the claim transfer in ``takeover_transfer`` and the UI shape in
``takeover_listing``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentBoardMessage, AuditLog, Project, WorkItem, WorkItemClaim, WorkItemTakeover
from ...time_utils import utc_now
from ..access_control import get_project_role_for_user
from ..agent_gateway.handoff_policy_keys import handoff_policy_from_config
from .claim_values import is_live
from .claims import active_claim
from .messages import ADMIN_ROLES, AUTHOR_HUMAN, Author, post_message
from .takeover_status import (
    AUTHOR_SYSTEM,
    CODE_ALREADY_HOLDER,
    CODE_NOT_CLAIMED,
    CODE_NOT_PENDING,
    CONFIRM_AUDIT_ACTION,
    DECIDED_BY_HUMAN,
    DECIDED_BY_SYSTEM,
    DECLINE_AUDIT_ACTION,
    DEFAULT_TTL,
    STATUS_CONFIRMED,
    STATUS_DECLINED,
    STATUS_PENDING,
    STATUSES,
    TRANSFER_AUDIT_ACTION,
    expire_pending,
)
from .takeover_transfer import _cancel, _require_still_applicable, _transfer_claim


async def _automatic(db: AsyncSession, claim: WorkItemClaim | None) -> bool:
    if claim is None:
        return False
    found = await db.execute(
        select(AgentBoardMessage.id).where(
            AgentBoardMessage.claim_id == claim.id, AgentBoardMessage.author_type == AUTHOR_SYSTEM
        )
    )
    return found.first() is not None


async def _pending_takeover(db: AsyncSession, work_item_id: str, requester_ref: str) -> WorkItemTakeover | None:
    """The requester's pending takeover of this item, if any."""
    return (
        await db.execute(
            select(WorkItemTakeover).where(
                WorkItemTakeover.work_item_id == work_item_id,
                WorkItemTakeover.requester_ref == requester_ref,
                WorkItemTakeover.status == STATUS_PENDING,
            )
        )
    ).scalar_one_or_none()


async def request_takeover(
    db: AsyncSession,
    *,
    item: WorkItem,
    to_user_id: str,
    to_agent_hash: str | None,
    to_agent_kind: str | None,
    reason: str | None,
    author: Author,
    message_to_user_id: str | None = None,
    require_claim: bool = True,
) -> WorkItemTakeover:
    """A pending takeover (new, or the requester's existing one) plus its ``handoff_request`` post. Flushes."""
    await expire_pending(db, work_item_id=item.id)
    requester_ref = to_agent_hash or f"user:{to_user_id}"
    existing = await _pending_takeover(db, item.id, requester_ref)
    if existing is not None:
        return existing
    claim = await active_claim(db, item.id)
    claim = claim if claim is not None and is_live(claim, utc_now()) else None
    if claim is None and require_claim:
        raise HTTPException(status_code=409, detail={"code": CODE_NOT_CLAIMED})
    if claim is not None and to_agent_hash and claim.holder_ref_hash == to_agent_hash:
        raise HTTPException(status_code=409, detail={"code": CODE_ALREADY_HOLDER})
    text = (reason or "").strip()
    message = await post_message(
        db,
        project_id=item.project_id,
        author=author,
        arguments={
            "kind": "handoff_request",
            "body": text or "Takeover requested.",
            "work_item_id": item.id,
            "to_user_id": message_to_user_id,
            "to_agent_hash": claim.holder_ref_hash if claim is not None and message_to_user_id is None else None,
        },
        allowed_kinds=frozenset({"handoff_request"}),
    )
    takeover = await _new_takeover(
        db, item=item, claim=claim, to_user_id=to_user_id, to_agent_hash=to_agent_hash,
        to_agent_kind=to_agent_kind, requester_ref=requester_ref, text=text, message=message,
    )
    try:
        async with db.begin_nested():
            db.add(takeover)
            await db.flush()
    except IntegrityError:
        raced = await _pending_takeover(db, item.id, requester_ref)
        if raced is None:
            raise HTTPException(status_code=409, detail={"code": CODE_NOT_PENDING}) from None
        return raced
    return takeover


async def _new_takeover(
    db: AsyncSession,
    *,
    item: WorkItem,
    claim: WorkItemClaim | None,
    to_user_id: str,
    to_agent_hash: str | None,
    to_agent_kind: str | None,
    requester_ref: str,
    text: str,
    message: AgentBoardMessage,
) -> WorkItemTakeover:
    """The pending row of a new request, under the Workspace's handoff policy (not yet added)."""
    now = utc_now()
    project = await db.get(Project, item.project_id)
    policy, _source = handoff_policy_from_config(project.config if project is not None else None)
    return WorkItemTakeover(
        id=str(uuid.uuid4()),
        project_id=item.project_id,
        work_item_id=item.id,
        from_claim_id=claim.id if claim else None,
        from_user_id=claim.holder_user_id if claim else None,
        from_agent_hash=claim.holder_ref_hash if claim else None,
        to_user_id=to_user_id,
        to_agent_hash=to_agent_hash,
        to_agent_kind=to_agent_kind,
        requester_ref=requester_ref,
        reason=text or None,
        automatic=await _automatic(db, claim),
        message_id=message.id,
        status=STATUS_PENDING,
        policy_mode=policy.mode,
        expires_at=now + DEFAULT_TTL,
        created_at=now,
    )


async def may_decide_takeover(db: AsyncSession, takeover: WorkItemTakeover, user_id: str) -> bool:
    if takeover.to_user_id == user_id:
        return True
    return await get_project_role_for_user(db, user_id, takeover.project_id) in ADMIN_ROLES


async def decide_takeover(
    db: AsyncSession,
    *,
    takeover: WorkItemTakeover,
    user_id: str | None,
    confirm: bool,
    policy_snapshot: dict[str, Any] | None = None,
) -> WorkItemTakeover:
    """Confirm (transfer the claim) or decline; the caller checked membership. Flushes; the caller commits.

    ``user_id=None`` is the server deciding under the Workspace's ``auto`` handoff policy: no
    person check, ``decided_by_kind = system`` and the applied ``policy_snapshot`` are stored. The compare-and-set
    and the claim transfer are exactly the human ones.
    """
    system = user_id is None
    if not system and not await may_decide_takeover(db, takeover, user_id):
        raise HTTPException(status_code=403, detail="Only the receiving person or a Workspace admin may decide")
    now = utc_now()
    if confirm:
        await _require_still_applicable(db, takeover, now)
    status = STATUS_CONFIRMED if confirm else STATUS_DECLINED
    moved = await db.execute(
        update(WorkItemTakeover)
        .where(
            WorkItemTakeover.id == takeover.id,
            WorkItemTakeover.status == STATUS_PENDING,
            WorkItemTakeover.expires_at > now,
        )
        .values(status=status, decided_at=now, decided_by=user_id,
                decided_by_kind=DECIDED_BY_SYSTEM if system else DECIDED_BY_HUMAN, policy_snapshot=policy_snapshot)
        .execution_options(synchronize_session="fetch")
    )
    if moved.rowcount != 1:
        await expire_pending(db, work_item_id=takeover.work_item_id)
        raise HTTPException(status_code=409, detail={"code": CODE_NOT_PENDING})
    await db.refresh(takeover)
    details = {"takeover_id": takeover.id, "project_id": takeover.project_id, "work_item_id": takeover.work_item_id,
               "from_user_id": takeover.from_user_id, "to_user_id": takeover.to_user_id,
               "decided_by": takeover.decided_by_kind, "policy": policy_snapshot}
    # An audit row always names a user: a system decision is recorded under the requester's user.
    actor = user_id or takeover.to_user_id
    if not confirm:
        db.add(AuditLog(user_id=actor, action=DECLINE_AUDIT_ACTION, resource_type="work_item_takeover",
                        resource_id=takeover.id, details=details))
        await db.flush()
        return takeover
    await _apply_confirmation(db, takeover, user_id=user_id, system=system, actor=actor, details=details)
    return takeover


async def _apply_confirmation(
    db: AsyncSession, takeover: WorkItemTakeover, *, user_id: str | None, system: bool, actor: str,
    details: dict[str, Any],
) -> None:
    """Transfer the claim, retire competing requests, post ``handoff_accept`` and audit both users."""
    claim = await _transfer_claim(db, takeover)
    takeover.new_claim_id = claim.id if claim is not None else None
    if takeover.from_claim_id:
        # The other pending requests against the same (now transferred) claim no longer apply.
        await _cancel(db, ids_of=(WorkItemTakeover.from_claim_id == takeover.from_claim_id)
                      & (WorkItemTakeover.id != takeover.id))
    await post_message(
        db,
        project_id=takeover.project_id,
        author=Author(AUTHOR_SYSTEM, takeover.to_user_id) if system else Author(AUTHOR_HUMAN, user_id),
        arguments={"kind": "handoff_accept", "body": "Takeover confirmed.", "work_item_id": takeover.work_item_id,
                   "reply_to": takeover.message_id, "to_user_id": takeover.to_user_id,
                   "to_agent_hash": takeover.to_agent_hash},
        allowed_kinds=frozenset({"handoff_accept"}),
    )
    details = {**details, "new_claim_id": takeover.new_claim_id, "epoch": claim.epoch if claim else None}
    db.add(AuditLog(user_id=actor, action=CONFIRM_AUDIT_ACTION, resource_type="work_item_takeover",
                    resource_id=takeover.id, details=details))
    for affected in {takeover.from_user_id, takeover.to_user_id} - {None}:
        db.add(AuditLog(user_id=affected, action=TRANSFER_AUDIT_ACTION, resource_type="work_item_takeover",
                        resource_id=takeover.id, details=details))
    await db.flush()


async def list_takeovers(db: AsyncSession, *, project_id: str, status: str | None) -> list[WorkItemTakeover]:
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail="status must be one of: " + ", ".join(sorted(STATUSES)))
    await expire_pending(db)
    statement = select(WorkItemTakeover).where(WorkItemTakeover.project_id == project_id)
    if status:
        statement = statement.where(WorkItemTakeover.status == status)
    return list((await db.execute(statement.order_by(WorkItemTakeover.created_at.desc()).limit(200))).scalars())


__all__ = [
    "decide_takeover",
    "list_takeovers",
    "may_decide_takeover",
    "request_takeover",
]
