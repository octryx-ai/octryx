"""A workflow run started by an Automation Action (incident / alert analysis)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FailedTaskRun, Session, TaskRun, User, WorkflowRun, WorkflowRunEvent
from ...time_utils import utc_now
from .alert_context import alert_run_context
from .records import WorkflowRunError, bind_session, lock_run, lock_run_id, main_session_id, record_event
from .states import (
    ACTION_TURN_PAUSE_REASONS,
    ACTIVE_STATUSES,
    EVENT_RESUMED,
    KIND_PHASED,
    PAUSE_CONTENT_BLOCKED,
    PAUSE_RUNTIME_FAILED,
    STATUS_PAUSED,
    STATUS_RUNNING,
)

logger = logging.getLogger(__name__)

ACTION_CONFIG_KEY = "workflow_run"
EVENT_STARTED_BY_ACTION = "started_by_action"
EVENT_ACTION_RUN_REUSED = "action_run_reused"
EVENT_ACTION_TURN_REDRIVEN = "action_turn_redriven"
_ATTEMPT_EVENTS = (EVENT_STARTED_BY_ACTION, EVENT_ACTION_RUN_REUSED)
TRIGGER_WORKFLOW_CONTINUE = "workflow_continue"
RUN_INPUT_WORKFLOW_RUN_KEY = "workflow_run_id"
REDRIVE_STATE_KEY = "action_redrive"
REFUSAL_RUN_ENDED = "action_workflow_run_ended"


def action_run_config(task: Any) -> dict[str, Any] | None:
    raw = dict(getattr(task, "config", None) or {}).get(ACTION_CONFIG_KEY)
    return dict(raw) if isinstance(raw, dict) and str(raw.get("workflow_key") or "").strip() else None


async def _prior_attempt_ids(db: AsyncSession, task_run: Any) -> list[str]:
    if task_run is None or getattr(task_run, "trigger_type", None) != "retry" or not task_run.trigger_id:
        return []
    failed = await db.get(FailedTaskRun, task_run.trigger_id)
    return [failed.task_run_id] if failed is not None and failed.task_run_id else []


def _redrive_run_id(task_run: Any) -> str | None:
    if task_run is None or getattr(task_run, "trigger_type", None) != TRIGGER_WORKFLOW_CONTINUE:
        return None
    payload = task_run.input_ if isinstance(task_run.input_, dict) else {}
    return str(payload.get(RUN_INPUT_WORKFLOW_RUN_KEY) or "") or None


async def prior_action_run(db: AsyncSession, *, task: Any, task_run: Any,
                           alert: dict[str, Any] | None) -> WorkflowRun | None:
    detail = WorkflowRunEvent.detail
    same: list[Any] = []
    redrive = _redrive_run_id(task_run)
    if redrive:
        same.append(WorkflowRunEvent.run_id == redrive)
    event_id = str((alert or {}).get("event_id") or "")
    if event_id:
        same.append(detail["alert_event_id"].as_string() == event_id)
    prior = await _prior_attempt_ids(db, task_run)
    if prior:
        same.append(detail["task_run_id"].as_string().in_(prior))
    if not same:
        return None
    run_id = (await db.execute(
        select(WorkflowRunEvent.run_id)
        .where(WorkflowRunEvent.kind.in_(_ATTEMPT_EVENTS), detail["task_id"].as_string() == str(task.id), or_(*same))
        .order_by(WorkflowRunEvent.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return await db.get(WorkflowRun, run_id) if run_id else None


def _attempt_detail(task: Any, task_run: Any, alert: dict[str, Any] | None) -> dict[str, Any]:
    return {"task_id": task.id, "task_run_id": getattr(task_run, "id", None),
            "trigger_type": getattr(task_run, "trigger_type", None),
            "alert_event_id": (alert or {}).get("event_id") or None,
            "alert": bool(alert), "test": bool((alert or {}).get("is_test"))}


async def _reuse_run(db: AsyncSession, run: WorkflowRun, *, task: Any, task_run: Any, session: Session,
                     alert: dict[str, Any] | None) -> WorkflowRun:
    from ...scheduler.execution.workflow_phase_turn import WorkflowPhasePreparationError

    run = await lock_run(db, run)
    if run.status not in ACTIVE_STATUSES:
        record_event(db, run, EVENT_ACTION_RUN_REUSED, node_id=run.current_node_id,
                     detail={**_attempt_detail(task, task_run, alert), "refused": REFUSAL_RUN_ENDED})
        await db.flush()
        raise WorkflowPhasePreparationError(REFUSAL_RUN_ENDED, reason=str(run.status))
    if run.status == STATUS_PAUSED and run.pause_reason in ACTION_TURN_PAUSE_REASONS:
        # Only the pause this module set for a failed turn is lifted by the next attempt; any other pause waits for
        # its person (the attempt's phase preparation then refuses, typed).
        was = run.pause_reason
        state = {key: value for key, value in dict(run.node_state or {}).items() if key != "pause"}
        run.status, run.pause_reason, run.node_state = STATUS_RUNNING, None, state
        record_event(db, run, EVENT_RESUMED, node_id=run.current_node_id,
                     detail={"from": was, "cause": getattr(task_run, "trigger_type", None) or "action",
                             "task_run_id": getattr(task_run, "id", None)})
    await bind_session(db, run, session, actor_id=None)
    record_event(db, run, EVENT_ACTION_RUN_REUSED, node_id=run.current_node_id,
                 detail=_attempt_detail(task, task_run, alert))
    await db.flush()
    return run


async def start_action_run(db: AsyncSession, *, task: Any, task_run: Any, session: Session,
                           alert: dict[str, Any] | None) -> WorkflowRun | None:
    from .engine import published_phased_flow
    from .records import start_run

    config = action_run_config(task)
    if config is None:
        return None
    existing = await prior_action_run(db, task=task, task_run=task_run, alert=alert)
    if existing is not None:
        return await _reuse_run(db, existing, task=task, task_run=task_run, session=session, alert=alert)
    if _redrive_run_id(task_run):
        from ...scheduler.execution.workflow_phase_turn import WorkflowPhasePreparationError

        # A re-drive names a run this Action did not start: never start one instead.
        raise WorkflowPhasePreparationError("action_workflow_phase_unavailable")
    if not task.project_id:
        from .access import workspace_required_error

        raise workspace_required_error()  # before any lookup: typed like every run start
    key = str(config["workflow_key"]).strip()[:180]
    if await published_phased_flow(db, key, task.project_id) is None:
        raise WorkflowRunError("unknown_workflow", f"The Action names the workflow '{key}', which is not published.",
                               404)
    owner = await db.get(User, task.owner_id)
    if owner is None:
        raise WorkflowRunError("action_owner_missing", "The Action has no owner to decide its run.", 409)
    context = {**(alert_run_context(alert, now=utc_now()) if alert else {}),
               "jira_project_key": str(config.get("jira_project_key") or "").strip()[:40] or None}
    run = await start_run(db, user=owner, workflow_key=key, project_id=task.project_id,
                          repository=str(config.get("repository") or "").strip()[:500] or None, session=session,
                          context={name: value for name, value in context.items() if value},
                          runtime_target=config.get("runtime_target"))
    record_event(db, run, EVENT_STARTED_BY_ACTION, node_id=run.current_node_id,
                 detail=_attempt_detail(task, task_run, alert))
    await db.flush()
    return run


_PAUSE_MESSAGES = {
    PAUSE_CONTENT_BLOCKED: (
        "A content policy refused the content of the Action's agent turn (for example injected instructions in the "
        "alert it read as data). The turn was not retried: the same content would be refused again. Review the alert "
        "and the content-security decisions, then continue to run the phase again or abort the run."
    ),
    PAUSE_RUNTIME_FAILED: (
        "The Action's agent turn failed in the runtime ({code}) before the phase finished. Continue to run the phase "
        "again, or abort the run."
    ),
}
_RETRY_PENDING = " A scheduler retry is pending and continues this run by itself."


async def pause_failed_action_run(db: AsyncSession, run_id: str | None, *, content_blocked: bool, code: str | None,
                                  task_run: Any, retry_scheduled: bool) -> WorkflowRun | None:
    from .limits import pause_run

    run = await lock_run_id(db, run_id)
    if run is None or run.status != STATUS_RUNNING:
        return None
    reason = PAUSE_CONTENT_BLOCKED if content_blocked else PAUSE_RUNTIME_FAILED
    message = _PAUSE_MESSAGES[reason].format(code=str(code or "turn_failed")[:80])
    if retry_scheduled and not content_blocked:
        message += _RETRY_PENDING
    await pause_run(db, run, reason=reason, actor_id=None, detail={
        "message": message, "code": str(code or "")[:120] or None, "task_run_id": getattr(task_run, "id", None),
        "retry_scheduled": bool(retry_scheduled and not content_blocked),
        "resume": {"kind": "restart", "node_id": run.current_node_id},
    })
    await db.flush()
    return run


async def _action_of(db: AsyncSession, run: WorkflowRun) -> tuple[Any, TaskRun | None] | None:
    from ...models import Task

    row = (await db.execute(
        select(WorkflowRunEvent.detail)
        .where(WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_STARTED_BY_ACTION)
        .order_by(WorkflowRunEvent.created_at.asc())
        .limit(1)
    )).scalar_one_or_none()
    detail = dict(row or {})
    task = await db.get(Task, str(detail.get("task_id") or "")) if detail.get("task_id") else None
    if task is None:
        return None
    started = await db.get(TaskRun, str(detail.get("task_run_id") or "")) if detail.get("task_run_id") else None
    return task, started


def mark_redrive(run: WorkflowRun) -> None:
    run.context = {**dict(run.context or {}), REDRIVE_STATE_KEY: {"state": "pending", "at": utc_now().isoformat()}}


def _settle_redrive(run: WorkflowRun, state: str, **extra: Any) -> None:
    context = dict(run.context or {})
    marker = dict(context.get(REDRIVE_STATE_KEY) or {})
    run.context = {**context, REDRIVE_STATE_KEY: {**marker, "state": state, **extra}}


async def redrive_action_turn(db: AsyncSession, run: WorkflowRun, *, scheduler: Any | None = None) -> str | None:
    # The marker is committed before the queue call, so a second caller never queues the turn twice.
    from ...models import Session as AgentSession
    from .graph import NODE_PHASE, graph_for_run
    from .octryx.continuation_marker import _device_target

    if dict(dict(run.context or {}).get(REDRIVE_STATE_KEY) or {}).get("state") != "pending":
        return None
    run = await lock_run(db, run)
    if dict(dict(run.context or {}).get(REDRIVE_STATE_KEY) or {}).get("state") != "pending":
        return None
    node = ((await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
            if run.workflow_kind == KIND_PHASED else None)
    found = await _action_of(db, run)
    thread_id = await main_session_id(db, run)
    thread = await db.get(AgentSession, thread_id) if thread_id else None
    if (run.status != STATUS_RUNNING or node is None or node.kind != NODE_PHASE or found is None or thread is None
            or thread.user_id == run.requested_by or _device_target(thread) is not None):
        _settle_redrive(run, "not_needed")
        await db.commit()
        return None
    _settle_redrive(run, "queuing")
    await db.commit()
    run_id, node_id, identity = run.id, run.current_node_id, thread.user_id
    task, started = found
    run_input: dict[str, Any] = {RUN_INPUT_WORKFLOW_RUN_KEY: run_id}
    payload = started.input_ if started is not None and isinstance(started.input_, dict) else {}
    if isinstance(payload.get("inbound_alert"), dict):
        run_input["inbound_alert"] = payload["inbound_alert"]
    if scheduler is None:
        from ...runtime_lifecycle import get_task_scheduler

        scheduler = get_task_scheduler()
    task_run_id: str | None = None
    try:
        queued = await scheduler.run_task_now(task.id, trigger_type=TRIGGER_WORKFLOW_CONTINUE, trigger_id=run_id,
                                              started_by=identity, run_input=run_input)
        task_run_id = str((queued or {}).get("task_run_id") or "") or None
    except Exception:
        logger.warning("workflow_run.action_redrive_failed run_id=%s task_id=%s", run_id, task.id, exc_info=True)
    run = await lock_run_id(db, run_id)
    if run is None:
        return task_run_id
    _settle_redrive(run, "queued" if task_run_id else "failed", task_run_id=task_run_id)
    record_event(db, run, EVENT_ACTION_TURN_REDRIVEN, node_id=node_id,
                 detail={"task_id": task.id, "task_run_id": task_run_id,
                         "result": "queued" if task_run_id else "not_queued"})
    if task_run_id is None:  # nobody would drive the phase: say so on the run instead of staying ``running``
        await pause_failed_action_run(db, run.id, content_blocked=False, code="action_turn_not_queued", task_run=None,
                                      retry_scheduled=False)
    await db.commit()
    return task_run_id


async def is_action_started(db: AsyncSession, run: WorkflowRun) -> bool:
    return (await db.execute(
        select(WorkflowRunEvent.id)
        .where(WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_STARTED_BY_ACTION)
        .limit(1)
    )).scalar_one_or_none() is not None


__all__ = [
    "ACTION_CONFIG_KEY",
    "EVENT_ACTION_RUN_REUSED",
    "EVENT_ACTION_TURN_REDRIVEN",
    "EVENT_STARTED_BY_ACTION",
    "REFUSAL_RUN_ENDED",
    "RUN_INPUT_WORKFLOW_RUN_KEY",
    "TRIGGER_WORKFLOW_CONTINUE",
    "action_run_config",
    "is_action_started",
    "mark_redrive",
    "pause_failed_action_run",
    "prior_action_run",
    "redrive_action_turn",
    "start_action_run",
]
