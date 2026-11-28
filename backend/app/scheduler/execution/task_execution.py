"""Task execution flow for scheduler-dispatched runs."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.services.error_facts import error_text
from app.services.worker_pool.state import release_worker_assignment

from ...services.agent_definition_execution_outcomes import AgentDefinitionExecutionError
from ...services.circuit_breaker import resolve_failed_task_run
from ...services.content_security.refusal import TURN_ERROR_CONTENT_BLOCKED, turn_error_class
from ...services.runtime_ownership.process_identity import current_process_id
from ...services.secure_work.intake.registry import sync_task_types as intake_sync_task_types
from ...time_utils import utc_now
from ..tickets import (
    evaluate_task_dependencies as _evaluate_task_dependencies,
)
from .action_admission import ActionAdmissionError
from .task_run_finish import _deliver_output, _emit_webhook, _finalize_session_tree, _handle_failure
from .task_run_kinds import CONTENT_BLOCKED, _Outcome, _run_agent_turn, _run_intake, _run_steps

logger = logging.getLogger(__name__)


def _track_running_run(scheduler, task_id: str, task_run_id: str) -> None:
    running_runs = getattr(scheduler, "_running_task_run_ids", None)
    if isinstance(running_runs, dict):
        running_runs[task_id] = task_run_id


async def _skip_task_run(
    db, scheduler, task, *, task_run_id: str | None, trigger_type: str, trigger_id: str | None,
    output: dict, error: str, assigned_worker_id: str | None, queue_domain: str | None,
) -> None:
    from ...models import TaskQueueEntry, TaskRun

    if task_run_id:
        task_run = (await db.execute(select(TaskRun).where(TaskRun.id == task_run_id))).scalar_one_or_none()
        if task_run is None:
            logger.warning("[scheduler] Queued task run %s missing for task %s", task_run_id, task.id)
            return
        task_run.status = "skipped"
        task_run.output = output
        task_run.error = error
        task_run.started_at = task_run.started_at or utc_now()
        task_run.completed_at = utc_now()
    else:
        task_run = TaskRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            session_id=None,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            status="skipped",
            started_by=task.owner_id,
            input_=task.config or {},
            output=output,
            error=error,
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        db.add(task_run)
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == task_run.id))
    ).scalar_one_or_none()
    if queue_entry:
        queue_entry.completed_at = task_run.completed_at
        queue_entry.status = "completed"
    await release_worker_assignment(
        db,
        worker_id=assigned_worker_id,
        queue_entry=queue_entry,
        task_run=task_run,
        success=False,
        required_domain=queue_domain or "any",
    )
    await scheduler._refresh_queue_wait_estimates(db)
    await db.commit()


async def execute_task(
    *,
    scheduler,
    task_id: str,
    trigger_type: str = "manual",
    trigger_id: str | None = None,
    task_run_id: str | None = None,
    assigned_worker_id: str | None = None,
    queue_domain: str | None = None,
) -> None:
    """Execute one queued task run, including retries and channel delivery."""
    from ...models import Task

    if task_id in scheduler._active_task_ids:
        logger.warning(
            "[scheduler] Task %s already has a live worker in this process; skipping duplicate start", task_id
        )
        return
    scheduler._active_task_ids.add(task_id)
    current = asyncio.current_task()
    if current:
        scheduler._running_futures[task_id] = current
    session_factory = scheduler._get_session_factory()
    async with session_factory() as db:
        try:
            task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
            if not task or not task.is_active:
                logger.warning("[scheduler] Task %s not found or inactive", task_id)
                return
            skip = dict(scheduler=scheduler, task_run_id=task_run_id, trigger_type=trigger_type,
                        trigger_id=trigger_id, assigned_worker_id=assigned_worker_id, queue_domain=queue_domain)
            if not await _admitted_to_start(db, task, skip):
                return
            task_run = await _start_task_run(db, scheduler, task, task_run_id=task_run_id,
                                              trigger_type=trigger_type, trigger_id=trigger_id)
            if task_run is None:
                return
            outcome = _Outcome()
            await _run_task(db, scheduler, task, task_run, outcome, trigger_type=trigger_type, trigger_id=trigger_id)
            queue_entry = await _close_queue_entry(db, scheduler, task_run, assigned_worker_id=assigned_worker_id,
                                                   queue_domain=queue_domain)
            if task_run.status == "error":
                await _handle_failure(db, scheduler, task, task_run, queue_entry, outcome,
                                      trigger_type=trigger_type, trigger_id=trigger_id)
            await _deliver_output(db, task, task_run)
            task_run = await _emit_webhook(db, task, task_run, trigger_type=trigger_type)
            await _finalize_session_tree(db, scheduler, task, task_run)
            logger.info("[scheduler] Task %s (%s) completed: %s", task_id, task.name, task_run.status)
        finally:
            scheduler._active_task_ids.discard(task_id)
            scheduler._running_futures.pop(task_id, None)
            running_runs = getattr(scheduler, "_running_task_run_ids", None)
            if isinstance(running_runs, dict):
                running_runs.pop(task_id, None)


async def _admitted_to_start(db, task, skip: dict) -> bool:
    dependency_eval = await _evaluate_task_dependencies(db, task.id)
    if not dependency_eval["ready"]:
        await _skip_task_run(db, task=task, **skip, error="Task dependencies are not satisfied", output={
            "status": "blocked_by_dependencies", "unmet_dependencies": dependency_eval["unmet"]})
        logger.info("[scheduler] Task %s skipped because dependencies are unmet", task.id)
        return False
    # An emergency stop holds every new start in its scope, not only the runs it paused: a webhook Action
    # or a schedule would otherwise start again right after.
    from app.services.incident_response.safe_mode import is_blocked_by_safe_mode

    stopped, stop_reason = await is_blocked_by_safe_mode(db, project_id=task.project_id)
    if stopped:
        await _skip_task_run(db, task=task, **skip, error="An emergency stop holds new starts in this Workspace",
                             output={"status": "emergency_stop", "reason": stop_reason or ""})
        logger.info("[scheduler] Task %s not started: emergency stop", task.id)
        return False
    return True


async def _start_task_run(db, scheduler, task, *, task_run_id: str | None, trigger_type: str,
                          trigger_id: str | None):
    from ...models import TaskRun

    if task_run_id:
        task_run = (await db.execute(select(TaskRun).where(TaskRun.id == task_run_id))).scalar_one_or_none()
        if task_run is None:
            logger.warning("[scheduler] Queued task run %s missing for task %s", task_run_id, task.id)
            return None
        task_run.status = "running"
        task_run.started_at = task_run.started_at or utc_now()
        task_run.owner_process_id = current_process_id()
    else:
        task_run = TaskRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            session_id=None,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            status="running",
            started_by=task.owner_id,
            input_=task.config or {},
            started_at=utc_now(),
            owner_process_id=current_process_id(),
        )
        db.add(task_run)
    await db.commit()
    _track_running_run(scheduler, task.id, task_run.id)
    return task_run


async def _run_task(db, scheduler, task, task_run, outcome: _Outcome, *, trigger_type: str,
                    trigger_id: str | None) -> None:
    try:
        from ...models.project.task import TaskStep
        from ..dispatch.agent_definition_binding import require_bound_task_runnable

        # A bound Action that no longer is a governed agent run is refused before any
        # step or agent routing (typed ActionAdmissionError path below).
        await require_bound_task_runnable(db, task)
        has_steps = (await db.execute(select(TaskStep).where(
            TaskStep.task_id == task.id, TaskStep.is_enabled.is_(True)).limit(1))).scalars().first() is not None
        if has_steps:
            await _run_steps(db, scheduler, task, task_run, outcome, trigger_type=trigger_type)
        elif task.task_type in intake_sync_task_types():  # every Work source
            await _run_intake(db, task, task_run)
        else:
            await _run_agent_turn(db, scheduler, task, task_run, outcome, trigger_type=trigger_type)
        if task_run.status == "success" and trigger_type == "retry":
            await resolve_failed_task_run(db, trigger_id=trigger_id)
    except AgentDefinitionExecutionError as exc:
        # The task named an agent definition the platform will not
        # execute. The run fails with the typed state persisted on it,
        # rather than silently running without the configured agent.
        _refused(task_run, outcome, exc.code, "agent_definition_refusal", exc.as_metadata())
    except ActionAdmissionError as exc:
        # Refused before any session or model dispatch; fixed code only.
        _refused(task_run, outcome, exc.code, "action_admission_refusal", exc.as_metadata())
    except Exception as exc:
        _crashed(task_run, outcome, exc)


def _refused(task_run, outcome: _Outcome, code: str, key: str, metadata: dict) -> None:
    logger.error("[scheduler] Task %s refused: %s", task_run.task_id, code)
    task_run.status = "error"
    task_run.error = code
    task_run.output = {**dict(task_run.output or {}), "status": "error", "task_error": code, key: metadata}
    outcome.admission_refused = True


def _crashed(task_run, outcome: _Outcome, exc: Exception) -> None:
    failure = error_text("scheduled_task_failed", exc)
    logger.error("[scheduler] Task %s failed: %s", task_run.task_id, failure)
    task_run.status = "error"
    task_run.error = failure
    current_output = {**dict(task_run.output or {}), "status": "error", "task_error": failure}
    # A content refusal that reached the scheduler as its exception is typed by its class.
    if turn_error_class(exc) == TURN_ERROR_CONTENT_BLOCKED:
        task_run.error = CONTENT_BLOCKED
        current_output["task_error"] = CONTENT_BLOCKED
        current_output["turn_outcome"] = {"state": "failed", "reason": CONTENT_BLOCKED}
        outcome.content_blocked = True
    task_run.output = current_output


async def _close_queue_entry(db, scheduler, task_run, *, assigned_worker_id: str | None, queue_domain: str | None):
    from ...models import TaskQueueEntry

    task_run.completed_at = utc_now()
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == task_run.id))
    ).scalar_one_or_none()
    if queue_entry:
        queue_entry.completed_at = task_run.completed_at
        queue_entry.status = "completed" if task_run.status == "success" else "failed"
        queue_entry.last_error = task_run.error
        queue_entry.result_session_id = task_run.session_id
    await release_worker_assignment(
        db,
        worker_id=assigned_worker_id,
        queue_entry=queue_entry,
        task_run=task_run,
        success=task_run.status == "success",
        required_domain=queue_domain or "any",
    )
    await scheduler._refresh_queue_wait_estimates(db)
    await db.commit()
    return queue_entry


