"""Typed child execution and parent continuation use parent-first durable bindings."""
from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowHandoff, WorkflowRun
from ..records import WorkflowRunError
from . import owner_lifecycle, rules, service

logger = logging.getLogger(__name__)


async def lock_parent_chain(db: AsyncSession, parent_id: str) -> None:
    """A nested typed offer locks its outer ancestors first, checking observed relationships afterward."""
    chain, seen, cursor = [], set(), parent_id
    with db.no_autoflush:
        for _ in range(3):
            if cursor in seen:
                raise WorkflowRunError("handoff_changed", "The parent chain contains a cycle.", 409)
            seen.add(cursor)
            identity = (await db.execute(select(WorkflowRun.id, WorkflowRun.parent_run_id).where(
                WorkflowRun.id == cursor))).one_or_none()
            if identity is None:
                raise WorkflowRunError("handoff_changed", "The parent chain cannot be proved.", 409)
            chain.append(tuple(identity))
            cursor = identity.parent_run_id
            if cursor is None:
                break
        else:
            raise WorkflowRunError("handoff_changed", "The parent chain exceeds the bounded handoff depth.", 409)
        for run_id, expected_parent in reversed(chain):
            current = (await db.execute(select(WorkflowRun.id, WorkflowRun.parent_run_id).where(
                WorkflowRun.id == run_id).with_for_update())).one_or_none()
            if current is None or current.parent_run_id != expected_parent:
                raise WorkflowRunError("handoff_changed", "The parent chain changed while claiming it.", 409)


async def child_offer(db: AsyncSession, run: WorkflowRun) -> WorkflowHandoff | None:
    """Identify current AND historical receivers from durable relationships, never context alone."""
    if not run.parent_run_id or not run.parent_node_id:
        return None
    rows = (await db.execute(select(WorkflowHandoff).where(
        WorkflowHandoff.parent_run_id == run.parent_run_id,
        WorkflowHandoff.parent_node_id == run.parent_node_id))).scalars().all()
    for row in rows:
        if row.child_run_id == run.id or any(
                old.get("child_run_id") == run.id for old in list(row.owner_history or [])):
            return row
    if isinstance(dict(run.context or {}).get("handoff_binding"), dict):
        raise WorkflowRunError("stale_owner", "The typed receiver no longer has a durable offer binding.", 403)
    return None


async def prelock_receiver(db: AsyncSession, run: WorkflowRun) -> WorkflowHandoff | None:
    """Before child CAS or direct locks: suppress autoflush until the parent lock is acquired."""
    with db.no_autoflush:
        row = await child_offer(db, run)
        if row is None:
            return None
        await lock_parent_chain(db, row.parent_run_id)
        return row


async def guard_receiver(db: AsyncSession, run: WorkflowRun) -> WorkflowHandoff | None:
    """Run before continuation, dispatch and result writes; roles never substitute current rights."""
    if await prelock_receiver(db, run) is None:
        return None
    await db.flush()
    row = await child_offer(db, run)
    if row is None:
        return None
    marker = dict(dict(run.context or {}).get("handoff_binding") or {})
    binding = service.accepted_binding(row)
    binding.update(owner_epoch=marker.get("owner_epoch"), payload_hash=marker.get("payload_hash"))
    if marker.get("handoff_id") != row.id or marker.get("actor_id") != run.requested_by:
        raise WorkflowRunError("stale_owner", "The receiver execution marker changed.", 403)
    from .permissions import rights_evaluator

    try:
        current = await service.require_owner_binding(db, row.id, binding, rights_evaluator=rights_evaluator)
        parent = await db.get(WorkflowRun, row.parent_run_id, populate_existing=True)
        rules._parent_valid(parent, current)
        return current
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        raise WorkflowRunError(detail.get("reason", "stale_owner"),
                               detail.get("message", "Receiver authority could not be proved."),
                               error.status_code) from error


async def start_accepted_child(db: AsyncSession, binding: dict) -> dict:
    """Called only AFTER acceptance commits; claim the exact pending child before engine initialization."""
    from ..engine import _run_from
    from ..graph import graph_for_run
    from ..limits import initial_limits
    from ..records import lock_run, record_event

    child = await db.get(WorkflowRun, binding["child_run_id"])
    if child is None:
        return {"state": "held", "reason": "child_missing", **binding}
    await guard_receiver(db, child)
    row = await child_offer(db, child)
    if row is None or service.accepted_binding(row) != binding:
        raise WorkflowRunError("stale_owner", "The accepted start binding is no longer current.", 403)
    child = await lock_run(db, child)
    if child.waiting_kind != "handoff_commit_pending":
        return {"state": "started", "child_run_id": child.id, "receiver_session_id": row.receiver_session_id}
    graph = await graph_for_run(db, child)
    start = graph.start()
    if start is None:
        raise WorkflowRunError("needs_configuration", "The pinned child has no valid start node.", 409)
    from ....models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, child.work_item_id) if child.work_item_id else None
    await initial_limits(db, child, graph, item=item)
    child.status, child.waiting_kind = "running", None
    record_event(db, child, "handoff.execution_started", actor_id=child.requested_by,
                 detail={"handoff_id": row.id, "owner_epoch": row.owner_epoch})
    await _run_from(db, child, graph, start, actor_id=child.requested_by)
    await db.commit()
    return {"state": "started", "child_run_id": child.id, "receiver_session_id": row.receiver_session_id}


async def sweep_handoffs(db: AsyncSession) -> None:
    """Resume committed pending starts and terminal children without a child-first parent callback."""
    from ..engine import resolve_current_node
    from ..records import lock_run

    ids = list((await db.execute(select(WorkflowHandoff.id).join(
        WorkflowRun, WorkflowRun.id == WorkflowHandoff.parent_run_id).where(
        WorkflowHandoff.state.in_(("offered", "accepted", "rejected", "timed_out")),
        or_(and_(WorkflowRun.status == "waiting", WorkflowRun.waiting_kind == "handoff",
                 WorkflowRun.current_node_id == WorkflowHandoff.parent_node_id,
                 WorkflowRun.node_state["entry"].as_integer() == WorkflowHandoff.parent_entry),
            and_(WorkflowHandoff.detach.is_(True), WorkflowHandoff.state == "accepted"))))).scalars())
    await db.commit()  # No earlier worker claim may establish an inverted lock order.
    for handoff_id in ids:
        try:
            parent, row = await service.lock_handoff(db, handoff_id)
            if row.state == "offered":
                row = await owner_lifecycle.expire_handoff(db, row.id)
            if row.state == "accepted":
                child = await db.get(WorkflowRun, row.child_run_id)
                if child.waiting_kind == "handoff_commit_pending":
                    binding = service.accepted_binding(row)
                    await db.commit()
                    await start_accepted_child(db, binding)
                    continue
                if child.status in {"completed", "failed", "stopped"}:
                    await guard_receiver(db, child)
                    facts = await owner_lifecycle.child_finished(db, row.id, owner_epoch=row.owner_epoch)
                    # Parent first already held; preserve its original Session rather than binding the receiver.
                    if not facts["detached"]:
                        await lock_run(db, parent)
                        value = facts["outcome"] if facts["status"] == "completed" else "blocked"
                        await resolve_current_node(db, parent, value or "blocked", actor_id=None)
            elif row.state in {"rejected", "timed_out"}:
                rules._parent_valid(parent, row)
                await lock_run(db, parent)
                await resolve_current_node(db, parent, "blocked", actor_id=None)
            await db.commit()
        except (WorkflowRunError, HTTPException) as error:
            await db.rollback()  # Hold safely; the offer and committed acceptance remain durable.
            detail = error.detail if isinstance(error, HTTPException) and isinstance(error.detail, dict) else {}
            code = error.code if isinstance(error, WorkflowRunError) else detail.get("reason", "held")
            if code == "not_handoff_recipient":
                await owner_lifecycle.revoke_owner(db, handoff_id, reason="current receiver membership was revoked")
                await db.commit()
            logger.warning("Workflow handoff held (%s)", code, extra={"handoff_id": handoff_id})


async def abort_children(db: AsyncSession, parent: WorkflowRun) -> None:
    """Parent action already owns its claim; typed detach and child stopping remain explicit."""
    ids = list((await db.execute(select(WorkflowHandoff.id).where(
        WorkflowHandoff.parent_run_id == parent.id,
        WorkflowHandoff.state.in_(("offered", "accepted", "owner_lost"))))).scalars())
    for handoff_id in ids:
        await owner_lifecycle.parent_aborted(db, handoff_id)


async def guard_tool_context(context) -> None:
    """Governed tool dispatch checks the actual Session's receiver, not a supplied tool argument."""
    from ..run_sessions import run_for_session

    if context.db is None or not context.session_id:
        return
    run = await run_for_session(context.db, context.session_id)
    if run is None or await child_offer(context.db, run) is None:
        return
    row = await guard_receiver(context.db, run)
    if (context.user_id != row.accepted_by or context.session_id != row.receiver_session_id
            or run.status not in {"running", "waiting", "paused"}):
        raise WorkflowRunError("stale_owner", "The tool call does not belong to the current receiver.", 403)


async def resolved_owner(db: AsyncSession, run: WorkflowRun) -> tuple[tuple[str, ...], str]:
    """An offered decision reads current durable ownership; its final writer locks/rechecks all rights."""
    from .authority import candidates

    row = await child_offer(db, run)
    marker = dict(dict(run.context or {}).get("handoff_binding") or {})
    if (row is None or row.state != "accepted" or row.child_run_id != run.id
            or row.accepted_by != run.requested_by or marker.get("owner_epoch") != row.owner_epoch
            or marker.get("payload_hash") != row.payload_hash):
        return (), "handoff_owner_unresolved"
    if row.accepted_by not in await candidates(db, row):
        return (), "handoff_owner_unresolved"
    return (row.accepted_by,), ""
