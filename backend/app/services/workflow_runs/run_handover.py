"""Handing a workflow run over to another person (Octryx companion, "watch, team and handovers").

- **Request** (the run's requester, or a platform admin): names the receiver (a member of the run's Workspace) and
  a reason; the run keeps working meanwhile. ``context.handover = {state: requested, from, to, reason, at, ...}``.
- **Accept** (only the receiver): the run's requester becomes the receiver (and its responsible person, when that
  was the old requester: ``accepted``); the run gets a new main chat thread of
  the receiver, its target is resolved again with ``auto`` for the receiver (device and seat first), a running
  device turn of the old thread is stopped and a running phase is entered again on the new target. A paused or
  waiting run keeps its state: the receiver decides it.
- **Decline** (only the receiver): the request ends; the run stays with its requester.

Every step is a run event and an audit row (who to whom, when, why). The work in progress travels with the run: the
old requester's device pushes ``octryx-wip/<run>`` when its turn stops (``octryx_claude.run_wip``), and the receiver's
runtime restores it when it prepares (device ``workspace_prep``, Server ``server_prepare``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkflowRun
from ...time_utils import utc_now, utc_now_aware
from .records import WorkflowRunError, record_event
from .states import ACTIVE_STATUSES, STATUS_RUNNING

CONTEXT_KEY = "handover"
STATE_REQUESTED, STATE_ACCEPTED, STATE_DECLINED = "requested", "accepted", "declined"
AUDIT_PREFIX = "workflow_run.handover"


def handover(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


def _set(run: WorkflowRun, value: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), CONTEXT_KEY: value}


def _audit(db: AsyncSession, run: WorkflowRun, action: str, actor_id: str, details: dict[str, Any]) -> None:
    db.add(AuditLog(user_id=actor_id, action=f"{AUDIT_PREFIX}.{action}", resource_type="workflow_run",
                    resource_id=run.id, details={"run_id": run.id, **details}))


async def request_handover(db: AsyncSession, run: WorkflowRun, *, user: User, to_user_id: str,
                           reason: str) -> dict[str, Any]:
    from ..admin.governance.admin_access_service import is_global_admin
    from ..attention.stream import nudge_after_commit
    from ..secure_work.access import work_scope_project_ids

    if run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("not_active", "The run has already ended.")
    if user.id != run.requested_by and not await is_global_admin(db, user.id):
        raise WorkflowRunError("not_requester", "Only the run's requester or an admin hands it over.", 403)
    receiver = await db.get(User, to_user_id) if to_user_id else None
    if receiver is None or receiver.id == run.requested_by or not receiver.is_active:
        raise WorkflowRunError("handover_receiver_invalid", "Choose another active person of the Workspace.", 422)
    scope = await work_scope_project_ids(db, receiver)
    if scope is not None and run.project_id not in scope:
        raise WorkflowRunError("handover_receiver_not_member", "The receiver is not a member of this Workspace.", 422)
    reason = str(reason or "").strip()[:500]
    if not reason:
        raise WorkflowRunError("handover_reason_required", "Say why the run is handed over.", 422)
    value = {"state": STATE_REQUESTED, "from": run.requested_by, "to": receiver.id, "requested_by": user.id,
             "reason": reason, "at": utc_now_aware().isoformat(), "branch": run.branch}
    _set(run, value)
    record_event(db, run, "handover_requested", node_id=run.current_node_id, actor_id=user.id,
                 detail={"to": receiver.id, "reason": reason})
    _audit(db, run, "requested", user.id, {"from": run.requested_by, "to": receiver.id, "reason": reason})
    nudge_after_commit(db, receiver.id, run_id=run.id, event="handover_requested")
    return value


def _pending_for(run: WorkflowRun, user: User) -> dict[str, Any]:
    value = handover(run)
    if value.get("state") != STATE_REQUESTED or run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("no_handover", "Nothing is waiting to be handed over to you here.", 409)
    if value.get("to") != user.id:
        raise WorkflowRunError("not_receiver", "Only the person it is handed over to decides.", 403)
    return value


async def decline_handover(db: AsyncSession, run: WorkflowRun, *, user: User, reason: str = "") -> None:
    from ..attention.stream import nudge_after_commit

    value = _pending_for(run, user)
    _set(run, {**value, "state": STATE_DECLINED, "decided_at": utc_now_aware().isoformat(),
               "decline_reason": str(reason or "")[:500]})
    record_event(db, run, "handover_declined", node_id=run.current_node_id, actor_id=user.id,
                 detail={"by": user.id})
    _audit(db, run, "declined", user.id, {"from": value.get("from"), "to": user.id})
    nudge_after_commit(db, value.get("requested_by"), run_id=run.id, event="handover_declined")


async def accept_handover(db: AsyncSession, run: WorkflowRun, *, user: User) -> dict[str, Any]:
    from .graph import NODE_PHASE, graph_for_run
    from .pause import _stop_device_turn
    from .records import bind_session, lock_run, new_chat_session
    from .runtime_target.server_build import refuse_server_build, run_definition
    from .runtime_target.target import CONTEXT_KEY as TARGET_KEY
    from .runtime_target.target import KIND_DEVICE, apply_to_thread, stored_target, validate_target

    value = _pending_for(run, user)
    run = await lock_run(db, run)
    # The receiver's runtime (``auto``) is known before anything changes: a run that builds or tests never moves onto
    # the server; the refusal leaves the handover pending.
    target = await validate_target(db, user=user, project_id=run.project_id, raw={"kind": "auto"},
                                   repository=run.repository)
    definition = await run_definition(db, run)
    refuse_server_build(target, workflow_key=run.workflow_key, where="handover_accept", definition=definition,
                        actor_id=user.id, db=db, run=run)
    previous_owner, previous_target = run.requested_by, stored_target(run)
    await _stop_device_turn(db, run, actor_id=user.id)
    thread = await new_chat_session(db, user, run.project_id)
    await bind_session(db, run, thread, actor_id=user.id)
    run.requested_by = user.id
    if run.responsible_user_id in (None, previous_owner):
        # The receiver also takes the old requester's responsibility; a person who took the
        # run over (or the Work item's resolved person) stays responsible.
        run.responsible_user_id, run.responsible_source = user.id, "accepted"
    run.context = {**dict(run.context or {}), TARGET_KEY: {**dict(target or {}), "chosen_by": user.id,
                                                          "at": utc_now().isoformat()}}
    apply_to_thread(thread, target)
    left_on_device = bool(previous_target and previous_target.get("kind") == KIND_DEVICE)
    accepted = {**value, "state": STATE_ACCEPTED, "decided_at": utc_now_aware().isoformat(), "session_id": thread.id,
                "target_reason": (target or {}).get("reason")}
    _set(run, accepted)
    record_event(db, run, "handover_accepted", node_id=run.current_node_id, actor_id=user.id, detail={
        "from": previous_owner, "to": user.id, "reason": value.get("reason"),
        "runtime_target": (target or {}).get("reason"),
        **({"wip": dict(dict(run.context or {}).get("wip") or {}) or None,
            "note": ("the previous owner's device pushes its work in progress (octryx-wip/<run>) when its turn stops; "
                     "the receiver's runtime restores it when it prepares")} if left_on_device else {}),
    })
    _audit(db, run, "accepted", user.id, {"from": previous_owner, "to": user.id, "reason": value.get("reason"),
                                          "runtime_target": (target or {}).get("reason")})
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    if run.status == STATUS_RUNNING and node is not None and node.kind == NODE_PHASE:
        from .engine import restart_at

        await restart_at(db, run, node.id, actor_id=user.id)  # the phase runs again where the receiver works
    return accepted


async def pending_for_user(db: AsyncSession, user: User) -> list[WorkflowRun]:
    """Active runs whose handover waits for ``user``."""
    from sqlalchemy import select

    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.status.in_(tuple(ACTIVE_STATUSES)),
        WorkflowRun.context[CONTEXT_KEY]["to"].as_string() == user.id,
    ).limit(50))).scalars().all()
    return [run for run in rows if handover(run).get("state") == STATE_REQUESTED]


__all__ = ["CONTEXT_KEY", "accept_handover", "decline_handover", "handover", "pending_for_user",
           "request_handover"]
