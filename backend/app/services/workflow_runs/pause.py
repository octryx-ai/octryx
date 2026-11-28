"""How a paused run goes on: the requester (or an admin) decides."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun, WorkflowRunDecision
from ...models.runtime.secure_work import WorkItem
from ...time_utils import utc_now
from .graph import NODE_PHASE, graph_for_run
from .limits import BUDGET_CEILING_FACTOR, loop_ceiling
from .records import WorkflowRunError, lock_run_id, record_event
from .states import (
    ACTIVE_STATUSES,
    EVENT_DECISION,
    EVENT_STOPPED,
    OUTCOME_STOPPED,
    PAUSE_BUDGET_LIMIT,
    ROUND_LIMIT_REASONS,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    STATUS_WAITING,
)

MAX_BUDGET_FACTOR = 3


def payload_hash(payload: Any) -> str:
    return "sha256:" + sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def record_decision(
    db: AsyncSession, run: WorkflowRun, *, kind: str, subject: str, action: str, payload: dict[str, Any],
    user_id: str | None, approval_id: str | None = None,
) -> WorkflowRunDecision:
    decision = WorkflowRunDecision(
        run_id=run.id, node_id=run.current_node_id, kind=kind, subject=subject, action=action, payload=payload,
        payload_hash=payload_hash(payload), approval_id=approval_id, decided_by=user_id,
    )
    db.add(decision)
    record_event(db, run, EVENT_DECISION, node_id=run.current_node_id, actor_id=user_id,
                 detail={"kind": kind, "subject": subject, "action": action})
    return decision


def _pause(run: WorkflowRun) -> dict[str, Any]:
    if run.status != STATUS_PAUSED:
        raise WorkflowRunError("not_paused", "The run is not paused.")
    return dict(dict(run.node_state or {}).get("pause") or {})


def loop_headroom(run: WorkflowRun, ceiling: int) -> int:
    pause = dict(dict(run.node_state or {}).get("pause") or {})
    counter = dict(dict(run.loop_counters or {}).get(str(pause.get("edge_id") or "")) or {})
    return max(ceiling - int(counter.get("limit") or 0), 0)


# Every way a pause can go on; a kind outside this set is refused, never a silent "running" that nothing continues.
RESUME_RETRY_ACTION = "retry_action"
RESUME_KINDS = frozenset({"edge", "phase_passed", "restart", "stay", "continue", "rerun", "approval", "waiting",
                          RESUME_RETRY_ACTION})


async def _resume(db: AsyncSession, run: WorkflowRun, resume: dict[str, Any], *, actor_id: str) -> None:
    from .engine import resolve_current_node, take_pending_edge

    kind = str(resume.get("kind") or "")
    if kind not in RESUME_KINDS:
        raise WorkflowRunError("unknown_resume", f"The pause names no known way to go on ({kind or 'none'}): "
                                                 "change the plan or abort the run.", 409)
    run.pause_reason = None
    if kind == "edge":
        await take_pending_edge(db, run, str(resume.get("edge_id") or ""), actor_id=actor_id)
    elif kind == "phase_passed":
        await resolve_current_node(db, run, None, actor_id=actor_id)
    elif kind == RESUME_RETRY_ACTION:
        from .engine import restart_at

        await restart_at(db, run, str(resume.get("node_id") or run.current_node_id or ""), actor_id=actor_id)
    elif kind in ("restart", "stay"):
        from .engine import restart_at

        # A new pass through the node, no loop iteration consumed; a phase paused at its budget needs a new turn too.
        await restart_at(db, run, str(resume.get("node_id") or run.current_node_id or ""), actor_id=actor_id)
    elif kind == "continue":
        from .octryx.same_pass import continue_pass

        await continue_pass(db, run, str(resume.get("node_id") or run.current_node_id or ""), actor_id=actor_id)
    elif kind == "rerun":
        from .engine import rerun_current_node

        await rerun_current_node(db, run, actor_id=actor_id)
    elif kind == "approval":
        from .graph import graph_for_run
        from .hitl_actions import prepare_decision

        node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
        run.status, run.waiting_kind = STATUS_WAITING, "awaiting_approval"
        if node is not None:
            await prepare_decision(db, run, node, actor_id=actor_id)
    elif kind == "waiting":
        run.status, run.waiting_kind = STATUS_WAITING, str(resume.get("waiting_kind") or "")
        state = dict(run.node_state or {})
        waiting = dict(state.get("waiting") or {})
        waiting["since"] = utc_now().isoformat()
        run.node_state = {**state, "waiting": waiting}


async def continue_run(db: AsyncSession, run: WorkflowRun, *, user: User, k: int, is_admin: bool) -> None:
    pause = _pause(run)
    if str(dict(pause.get("resume") or {}).get("kind") or "") == RESUME_RETRY_ACTION:
        from .action_failures import ACTION_RETRY, decide

        await decide(db, run, user=user, action=ACTION_RETRY, body={})
        await _mark_action_redrive(db, run)
        return
    if type(k) is not int or k < 1:
        raise WorkflowRunError("invalid_k", "Continue needs a whole number of at least 1.", 422)
    if run.pause_reason in ROUND_LIMIT_REASONS:
        ceiling = await loop_ceiling(db)
        headroom = loop_headroom(run, ceiling)
        if k > headroom:
            raise WorkflowRunError(
                "beyond_ceiling",
                f"At most {headroom} more iteration(s) fit under the platform ceiling of {ceiling}; "
                "a platform admin can raise the ceiling.", 422)
        edge_id = str(pause.get("edge_id") or "")
        counters = dict(run.loop_counters or {})
        counter = dict(counters.get(edge_id) or {})
        counter["limit"] = int(counter.get("limit") or 0) + k
        from .size_class.loops import RAISED_KEY

        counter[RAISED_KEY] = True  # a person's rounds: a size class's own rounds no longer bind this loop
        counters[edge_id] = counter
        run.loop_counters = counters
        record_decision(db, run, kind="pause", subject=run.pause_reason, action="continue",
                        payload={"edge_id": edge_id, "k": k, "limit": counter["limit"]}, user_id=user.id)
    elif run.pause_reason == PAUSE_BUDGET_LIMIT:
        if k > MAX_BUDGET_FACTOR:
            raise WorkflowRunError("invalid_k", f"The budget grows by at most {MAX_BUDGET_FACTOR} times.", 422)
        limits = dict(run.limits or {})
        budget, ceiling = dict(limits.get("budget") or {}), dict(limits.get("budget_ceiling") or {})
        base = {key: value / BUDGET_CEILING_FACTOR for key, value in ceiling.items()}
        for key in pause.get("keys") or []:
            step = float(base.get(key) or budget.get(key) or 0)
            raised = float(budget.get(key) or 0) + step * k
            if not is_admin and not ceiling.get(key):
                raise WorkflowRunError(
                    "beyond_budget_ceiling",
                    f"The {key} budget comes from the Work item and has no workflow ceiling; an admin decides.", 422)
            if not is_admin and raised > float(ceiling[key]):
                raise WorkflowRunError(
                    "beyond_budget_ceiling",
                    f"The {key} budget would exceed its ceiling of {ceiling[key]}; an admin decides beyond it.", 422)
            budget[key] = raised
        run.limits = {**limits, "budget": budget}
        record_decision(db, run, kind="pause", subject=PAUSE_BUDGET_LIMIT, action="continue",
                        payload={"keys": pause.get("keys"), "k": k, "budget": budget}, user_id=user.id)
    else:
        record_decision(db, run, kind="pause", subject=str(run.pause_reason or ""), action="continue",
                        payload={"k": k}, user_id=user.id)
    await _resume(db, run, dict(pause.get("resume") or {}), actor_id=user.id)
    await _mark_action_redrive(db, run)


async def _mark_action_redrive(db: AsyncSession, run: WorkflowRun) -> None:
    from .automation import is_action_started, mark_redrive

    if run.status == STATUS_RUNNING and await is_action_started(db, run):
        mark_redrive(run)


async def change_plan(db: AsyncSession, run: WorkflowRun, *, user: User, is_admin: bool = False) -> None:
    from .engine import restart_at

    _pause(run)
    changes = int(dict(run.context or {}).get("plan_changes") or 0)
    ceiling = await loop_ceiling(db)
    if changes >= ceiling and not is_admin:
        raise WorkflowRunError(
            "plan_change_limit",
            f"The plan was changed {changes} times, the platform ceiling; an admin decides about another change.",
            422)
    graph = await graph_for_run(db, run)
    version_plan = graph.plan_node
    ordered = [node.id for node in graph.ordered_nodes()]
    plan = version_plan if version_plan in graph.nodes else next(
        (node.id for node in graph.ordered_nodes() if node.kind == NODE_PHASE), "")
    if not plan:
        raise WorkflowRunError("no_plan_phase", "The workflow has no phase to return to.")
    start = ordered.index(plan)
    counters = dict(run.loop_counters or {})
    for edge_id, counter in counters.items():
        if counter.get("target") in ordered and ordered.index(counter["target"]) >= start:
            counters[edge_id] = {**counter, "used": 0}
    run.loop_counters = counters
    run.context = {**dict(run.context or {}), "plan_changes": changes + 1}
    from .wip_reset import EVENT_REQUESTED, request_reset

    phases = [node.id for node in graph.ordered_nodes() if node.kind == NODE_PHASE]
    if reset := request_reset(run, plan, phases):
        record_event(db, run, EVENT_REQUESTED, node_id=plan, actor_id=user.id, detail={"sha": reset})
    record_decision(db, run, kind="pause", subject=str(run.pause_reason or ""), action="change_plan",
                    payload={"plan_node": plan, "plan_changes": changes + 1}, user_id=user.id)
    await restart_at(db, run, plan, actor_id=user.id)
    await _mark_action_redrive(db, run)


MAX_STOP_REASON = 500


def stop_reason(raw: Any) -> str:
    reason = " ".join(str(raw or "").split())
    if not reason:
        raise WorkflowRunError("stop_reason_required", "Say why the run stops; the reason is recorded.", 422)
    return reason[:MAX_STOP_REASON]


def record_stop(run: WorkflowRun, *, reason: str, user_id: str | None, via: str) -> None:
    run.context = {**dict(run.context or {}), "stop": {
        "reason": reason, "by": user_id, "at": utc_now().isoformat(), "via": via, "node_id": run.current_node_id,
        "was": str(run.pause_reason or run.waiting_kind or run.status)}}


async def abort_run(db: AsyncSession, run: WorkflowRun, *, user: User, reason: str) -> None:
    if run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("not_active", "The run has already ended.")
    reason = stop_reason(reason)
    record_decision(db, run, kind="pause" if run.status == STATUS_PAUSED else "abort",
                    subject=str(run.pause_reason or run.waiting_kind or run.status), action="abort",
                    payload={"reason": reason}, user_id=user.id)
    record_stop(run, reason=reason, user_id=user.id, via="abort")
    child_id = str(dict(run.node_state or {}).get("child_run_id") or "")
    delivered = _delivered(run)  # read before the status changes below
    run.status, run.outcome, run.completed_at = STATUS_STOPPED, OUTCOME_STOPPED, utc_now()
    run.waiting_kind = None
    record_event(db, run, EVENT_STOPPED, node_id=run.current_node_id, actor_id=user.id, detail={"reason": reason})
    await _stop_device_turn(db, run, actor_id=user.id)
    from .handoff.lifecycle import abort_children

    await abort_children(db, run)
    child = await lock_run_id(db, child_id)
    if child is not None and child.status in ACTIVE_STATUSES:
        await abort_run(db, child, user=user, reason=f"The parent run was aborted: {reason}")
    if run.work_item_id and not run.parent_run_id:
        if delivered:
            record_event(db, run, EVENT_DECISION, actor_id=user.id, detail={
                "kind": "work_item_state", "to_state": None, "result": "kept: pull request open"})
        else:
            await _block_work_item(db, run, user)
    if run.parent_run_id:
        from .sub_workflows import child_finished

        await child_finished(db, run, actor_id=user.id)


async def _stop_device_turn(db: AsyncSession, run: WorkflowRun, *, actor_id: str) -> None:
    from app.services.devices.job_state import BUSY_STATUSES

    from ..devices.jobs import request_stop, thread_job
    from .records import main_session_id

    thread_id = await main_session_id(db, run)
    job = await thread_job(db, thread_id) if thread_id else None
    if job is not None and job.status in BUSY_STATUSES:
        await request_stop(db, job, actor_id=actor_id)
    from .teamwork.item_stop import stop_jobs

    await stop_jobs(db, run, actor_id=actor_id)


def _delivered(run: WorkflowRun) -> bool:
    # Aborting the watch of a delivered run must not turn its item red.
    from .states import WAITING_WATCH

    pull_request = dict(run.pull_request or {})
    return (run.status == STATUS_WAITING and run.waiting_kind == WAITING_WATCH and bool(pull_request.get("id"))
            and str(pull_request.get("state") or "open") == "open")


async def _block_work_item(db: AsyncSession, run: WorkflowRun, user: User) -> None:
    from ..secure_work.lifecycle_transitions import auto_transition_work_item

    item = await db.get(WorkItem, run.work_item_id)
    if item is not None:
        stop = dict(dict(run.context or {}).get("stop") or {})
        result = await auto_transition_work_item(db, item=item, current_user=user, to_state="blocked",
                                                 reason=f"Workflow run '{run.title}' was aborted: {stop.get('reason')}")
        record_event(db, run, EVENT_DECISION, actor_id=user.id,
                     detail={"kind": "work_item_state", "to_state": "blocked",
                             "result": result.get("status"), "reason": result.get("reason")})


__all__ = ["abort_run", "change_plan", "continue_run", "loop_headroom", "payload_hash", "record_decision",
           "record_stop", "stop_reason"]
