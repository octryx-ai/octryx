"""The owner lifecycle of an offered or accepted handoff: expiry (and the deputy round), a lost owner, the parent's
abort and the child's terminal outcome."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.workflow_handoff import WorkflowHandoff
from ....time_utils import utc_now
from ..records import record_event
from .contract import canonical_hash, owner_ref, refuse
from .rules import _cas, _hash_valid, _parent_valid, _utc, binding_payload
from .service import lock_handoff


async def expire_handoff(db: AsyncSession, handoff_id: str) -> WorkflowHandoff:
    parent, row = await lock_handoff(db, handoff_id)
    _hash_valid(row)
    if row.state != "offered" or _utc(utc_now()) < _utc(row.expires_at):
        return row
    _parent_valid(parent, row)
    expired_round = row.round
    deputy = row.contract.get("deputy")
    if deputy and not row.deputy_active:
        row.round += 1
        row.deputy_active = True
        row.target_kind, row.target_key = owner_ref(deputy, deputy=True)
        row.issued_at = utc_now()
        row.expires_at = row.issued_at + timedelta(seconds=row.contract["timeout_seconds"])
        row.payload_hash = canonical_hash(binding_payload(row))
        row.state_version += 1
        record_event(db, parent, "handoff.offered", node_id=row.parent_node_id,
            detail={"handoff_id": row.id, "round": row.round, "deputy": True, "payload_hash": row.payload_hash})
    else:
        await _cas(db, row, state="timed_out")
    record_event(db, parent, "handoff.timed_out", node_id=row.parent_node_id,
        detail={"handoff_id": row.id, "round": expired_round,
                "new_round": row.round if row.state == "offered" else None})
    await db.flush()
    return row


async def revoke_owner(db: AsyncSession, handoff_id: str, *, reason: str) -> WorkflowHandoff:
    parent, row = await lock_handoff(db, handoff_id)
    if row.state == "accepted":
        await _cas(db, row, state="owner_lost", owner_epoch=row.owner_epoch + 1)
        record_event(db, parent, "handoff.owner_lost", node_id=row.parent_node_id,
            detail={"handoff_id": row.id, "owner_epoch": row.owner_epoch, "reason": reason})
    return row


async def parent_aborted(db: AsyncSession, handoff_id: str) -> WorkflowHandoff:
    parent, row = await lock_handoff(db, handoff_id)
    if row.state in {"offered", "accepted", "owner_lost"} and not row.detach:
        await _cas(db, row, state="stopped", owner_epoch=row.owner_epoch + 1)
        if row.child_run_id:
            child = await db.get(WorkflowRun, row.child_run_id)
            if child and child.status not in {"completed", "failed", "stopped"}:
                child.status, child.outcome, child.waiting_kind = "stopped", "stopped", None
                child.state_version += 1
    record_event(db, parent, "handoff.parent_aborted", node_id=row.parent_node_id,
        detail={"handoff_id": row.id, "detached": row.detach})
    return row


async def child_finished(db: AsyncSession, handoff_id: str, *, owner_epoch: int) -> dict:
    parent, row = await lock_handoff(db, handoff_id)
    if row.state == "child_done":
        if row.owner_epoch != owner_epoch:
            refuse("stale_owner", "A stale owner cannot adopt the terminal handoff")
        return dict(row.child_outcome)
    if row.state != "accepted" or row.owner_epoch != owner_epoch:
        refuse("stale_owner", "A stale child cannot complete this handoff")
    child = await db.get(WorkflowRun, row.child_run_id, populate_existing=True)
    if not child or child.status not in {"completed", "failed", "stopped"}:
        refuse("child_not_terminal", "The child has no persisted terminal outcome")
    outcome = {"child_run_id": child.id, "status": child.status, "outcome": child.outcome,
               "parent_run_id": parent.id, "parent_node_id": row.parent_node_id, "parent_entry": row.parent_entry,
               "detached": row.detach, "owner_epoch": row.owner_epoch}
    await _cas(db, row, state="child_done", child_outcome=outcome)
    record_event(db, parent, "handoff.child_outcome", node_id=row.parent_node_id,
        detail={"handoff_id": row.id, **outcome})
    return outcome  # Root resumes the parent in a subsequent transaction, retaining its own Session.
