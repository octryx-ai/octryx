"""Task execution flow for scheduler-dispatched runs."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.services.error_facts import error_text
from app.services.worker_pool.state import release_worker_assignment

from ...agent.loops.response._loop_reply_contract import REASON_PATH_UNSUPPORTED, declares_checked_reply
from ...services.agent_definition_execution_outcomes import AgentDefinitionExecutionError
from ...services.circuit_breaker import escalate_failed_task_run_decision, resolve_failed_task_run
from ...services.content_security.refusal import TURN_ERROR_CONTENT_BLOCKED, turn_error_class
from ...services.outbound_webhook import emit_outbound_webhook_event
from ...services.runtime_ownership.process_identity import current_process_id
from ...services.secure_work.intake.registry import sync_task_types as intake_sync_task_types
from ...services.session.turn_final_outcome import (
    action_reply_verdict,
    action_stop_verdict,
    capture_trace_boundary,
    load_run_final_outcome,
    load_run_turn_error_class,
)
from ...time_utils import utc_now
from ..output import deliver_task_output_channel as _deliver_task_output_channel
from ..tickets import (
    build_task_session_metadata as _build_task_session_metadata,
)
from ..tickets import (
    detect_agent_failure as _detect_agent_failure,
)
from ..tickets import (
    evaluate_task_dependencies as _evaluate_task_dependencies,
)
from .action_admission import ActionAdmissionError, admit_agent_turn
from .inbound_alert_turn import (
    alert_prompt,
    alert_retry_identity,
    alert_session_metadata,
    finalize_alert_event,
    inbound_alert_of,
    suppress_delivery,
)

logger = logging.getLogger(__name__)

#: The closed error code of an Action run whose turn a content policy refused (terminal).
CONTENT_BLOCKED = "content_blocked"


def _track_running_run(scheduler, task_id: str, task_run_id: str) -> None:
    """Remember which run this process executes for ``task_id`` (cross-process cancel)."""
    running_runs = getattr(scheduler, "_running_task_run_ids", None)
    if isinstance(running_runs, dict):
        running_runs[task_id] = task_run_id


async def _skip_task_run(
    db, scheduler, task, *, task_run_id: str | None, trigger_type: str, trigger_id: str | None,
    output: dict, error: str, assigned_worker_id: str | None, queue_domain: str | None,
) -> None:
    """Record a run that does not start (``skipped`` with why) and release its queue entry and worker."""
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
    from ...models import Task, TaskQueueEntry, TaskRun

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
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if not task or not task.is_active:
                logger.warning("[scheduler] Task %s not found or inactive", task_id)
                return

            dependency_eval = await _evaluate_task_dependencies(db, task.id)
            if not dependency_eval["ready"]:
                await _skip_task_run(
                    db, scheduler, task, task_run_id=task_run_id, trigger_type=trigger_type, trigger_id=trigger_id,
                    output={"status": "blocked_by_dependencies", "unmet_dependencies": dependency_eval["unmet"]},
                    error="Task dependencies are not satisfied", assigned_worker_id=assigned_worker_id,
                    queue_domain=queue_domain,
                )
                logger.info("[scheduler] Task %s skipped because dependencies are unmet", task_id)
                return

            # An emergency stop holds every new start in its scope, not only the runs it paused: a webhook Action
            # or a schedule would otherwise start again right after.
            from app.services.incident_response.safe_mode import is_blocked_by_safe_mode

            stopped, stop_reason = await is_blocked_by_safe_mode(db, project_id=task.project_id)
            if stopped:
                await _skip_task_run(
                    db, scheduler, task, task_run_id=task_run_id, trigger_type=trigger_type, trigger_id=trigger_id,
                    output={"status": "emergency_stop", "reason": stop_reason or ""},
                    error="An emergency stop holds new starts in this Workspace", assigned_worker_id=assigned_worker_id,
                    queue_domain=queue_domain,
                )
                logger.info("[scheduler] Task %s not started: emergency stop", task_id)
                return

            if task_run_id:
                task_run = (await db.execute(select(TaskRun).where(TaskRun.id == task_run_id))).scalar_one_or_none()
                if task_run is None:
                    logger.warning("[scheduler] Queued task run %s missing for task %s", task_run_id, task_id)
                    return
                task_run.status = "running"
                task_run.started_at = task_run.started_at or utc_now()
                task_run.owner_process_id = current_process_id()
                await db.commit()
                _track_running_run(scheduler, task_id, task_run.id)
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
                _track_running_run(scheduler, task_id, task_run.id)

            # Set only by the typed refusal handlers below (exception provenance, never error text).
            admission_refused = False
            # Set only by the checked-reply verdict below (terminal, like an admission refusal).
            reply_contract_violation = False
            # Set only by the run's recorded runtime stop below (terminal as well).
            runtime_stopped = False
            # Set only by the turn's typed content-refusal class (trace class or exception type; terminal).
            content_blocked = False
            # The workflow run this attempt's Action turn runs in (started or continued), if any.
            action_run_id: str | None = None
            try:
                from ...models.project.task import TaskStep
                from ..dispatch.agent_definition_binding import require_bound_task_runnable

                # A bound Action that no longer is a governed agent run is refused before any
                # step or agent routing (typed ActionAdmissionError path below).
                await require_bound_task_runnable(db, task)
                steps_check = await db.execute(
                    select(TaskStep)
                    .where(
                        TaskStep.task_id == task.id,
                        TaskStep.is_enabled.is_(True),
                    )
                    .limit(1)
                )
                has_steps = steps_check.scalars().first() is not None

                if has_steps:
                    from ...models import Session as AgentSession
                    from .step_executor import StepExecutor

                    root_session = AgentSession(
                        id=str(uuid.uuid4()),
                        user_id=task.owner_id,
                        project_id=task.project_id,
                        agent_type=task.agent_type or "change",
                        status="active",
                        origin="scheduler",
                        metadata_={
                            "title": f"{task.name} · {task_run.id[:8]}",
                            "task_id": task.id,
                            "task_name": task.name,
                            "task_run_id": task_run.id,
                            "trigger": trigger_type,
                        },
                    )
                    db.add(root_session)
                    await db.flush()
                    task_run.session_id = root_session.id
                    await db.commit()

                    executor = StepExecutor(scheduler)
                    final_context = await executor.execute(db, task, task_run)

                    session_ids: list[str] = []
                    step_statuses: list[str] = []
                    for pos_key in sorted(final_context["steps"].keys(), key=int):
                        sr = final_context["steps"][pos_key]
                        session_ids.extend(sr.session_ids)
                        step_statuses.append(sr.status)

                    task_run.output = {
                        "mode": "step_executor",
                        "step_count": len(final_context["steps"]),
                        "step_statuses": step_statuses,
                        "session_ids": session_ids,
                    }
                    has_errors = any(s == "error" for s in step_statuses)
                    task_run.status = "error" if has_errors else "success"
                    # A step refused because its agent's reply format cannot be checked there is
                    # terminal like an admission refusal; other step refusals keep their retries.
                    if any(sr.error == REASON_PATH_UNSUPPORTED for sr in final_context["steps"].values()):
                        task_run.error = REASON_PATH_UNSUPPORTED
                        admission_refused = True

                elif task.task_type in intake_sync_task_types():  # every Work source
                    from ...services.secure_work.intake.scheduled import run_scheduled_intake

                    output = await run_scheduled_intake(db, task=task, task_run=task_run)
                    logger.info(
                        "[scheduler] %s task=%s imported=%s updated=%s status=%s",
                        task.task_type, task.id,
                        (output.get("summary") or {}).get("imported"),
                        (output.get("summary") or {}).get("updated"),
                        output.get("mode"),
                    )
                    task_run.status = "success"

                else:
                    from ...services.agent_definition_execution_outcomes import payload_resolution_metadata

                    # Type, raw values, owner-visible agent, its Workspace and a real
                    # instruction are admitted before any session or model dispatch (typed refusals).
                    admitted = await admit_agent_turn(db, task)
                    config = dict(task.config or {})
                    agent_definition_payload = admitted.agent_definition
                    runtime_target_id = admitted.runtime_target_id
                    thinking_level = admitted.thinking_level
                    prompt = admitted.prompt
                    session_metadata = _build_task_session_metadata(task, task_run.id, trigger=trigger_type)
                    # An alert-started run runs as the webhook's automation identity, with the
                    # alert attached as data beside the Action's own instruction.
                    inbound_alert = inbound_alert_of(task_run)
                    if inbound_alert:
                        prompt = alert_prompt(prompt, inbound_alert)
                        session_metadata.update(alert_session_metadata(inbound_alert))
                    # Record which agent-definition source produced the
                    # executed instructions on the canonical session metadata.
                    session_metadata.update(payload_resolution_metadata(agent_definition_payload))
                    coding_run = None
                    if agent_definition_payload:
                        from ...services.secure_work.coding_run import ensure_coding_run_work_item

                        coding_run = await ensure_coding_run_work_item(
                            db,
                            task=task,
                            task_run=task_run,
                            agent_definition=agent_definition_payload,
                            prompt=prompt,
                            trigger_type=trigger_type,
                        )
                        if coding_run:
                            session_metadata["coding_run_work_item_id"] = coding_run["work_item_id"]
                            session_metadata["coding_run"] = coding_run

                    checked_reply = declares_checked_reply(agent_definition_payload)
                    boundary = None

                    async def _session_ready(ready_session):
                        nonlocal boundary, action_run_id
                        # Every agent run's traces are the ones after this boundary, taken right
                        # before ``run_agent``; the session's history is never changed.
                        boundary = await capture_trace_boundary(db, ready_session.id)
                        # An Action naming a phased workflow runs its turn as the run's first phase.
                        from ...services.workflow_runs.automation import start_action_run

                        action_run = await start_action_run(db, task=task, task_run=task_run, session=ready_session,
                                                            alert=inbound_alert)
                        action_run_id = action_run.id if action_run is not None else None
                        return await scheduler._assign_task_run_session(db, task_run, ready_session.id)

                    session, result_payload = await scheduler._run_agent_for_task(
                        db,
                        task,
                        prompt,
                        agent_definition=agent_definition_payload,
                        runtime_target_id=runtime_target_id,
                        thinking_level=thinking_level,
                        session_metadata=session_metadata,
                        on_session_ready=_session_ready,
                        max_iterations=config.get("max_iterations"),
                        run_as_user_id=task_run.started_by if inbound_alert else None,
                        skip_session_reuse=bool(inbound_alert),
                    )
                    task_run.session_id = session.id
                    if coding_run:
                        from ...services.secure_work.coding_run import link_coding_run_session

                        await link_coding_run_session(
                            db,
                            work_item_id=coding_run["work_item_id"],
                            session_id=session.id,
                            task_run_id=task_run.id,
                        )
                    task_run.output = {
                        **result_payload,
                        **({"coding_run": coding_run} if coding_run else {}),
                    }
                    # A content-policy refusal is a permanent refusal of the turn's content (typed trace class).
                    turn_error = (
                        await load_run_turn_error_class(db, session.id, boundary) if boundary is not None else None
                    )
                    if turn_error == TURN_ERROR_CONTENT_BLOCKED:
                        task_run.output = {
                            **task_run.output, "turn_outcome": {"state": "failed", "reason": CONTENT_BLOCKED}
                        }
                        task_run.status = "error"
                        task_run.error = CONTENT_BLOCKED
                        content_blocked = True
                    elif checked_reply:
                        # A checked agent succeeds only on its run's single finished, satisfied final.
                        final = (
                            await load_run_final_outcome(db, session.id, boundary) if boundary is not None else None
                        )
                        reply_failure = action_reply_verdict(final)
                        task_run.output = {**task_run.output, "reply_contract": final.reply_contract if final else None}
                        task_run.status = "error" if reply_failure else "success"
                        task_run.error = reply_failure
                        reply_contract_violation = reply_failure is not None
                    else:
                        # A run whose own final trace recorded an explicit runtime stop fails with that
                        # closed reason; every other outcome keeps the text-based rule unchanged.
                        final = (
                            await load_run_final_outcome(db, session.id, boundary) if boundary is not None else None
                        )
                        stop_reason = action_stop_verdict(final)
                        if stop_reason is not None:
                            task_run.output = {
                                **task_run.output, "turn_outcome": {"state": "stopped", "reason": stop_reason}
                            }
                            task_run.status = "error"
                            task_run.error = stop_reason
                            runtime_stopped = True
                        else:
                            task_run.status = "error" if _detect_agent_failure(result_payload) else "success"

                if task_run.status == "success" and trigger_type == "retry":
                    await resolve_failed_task_run(db, trigger_id=trigger_id)

            except AgentDefinitionExecutionError as exc:
                # The task named an agent definition the platform will not
                # execute. The run fails with the typed state persisted on it,
                # rather than silently running without the configured agent.
                logger.error(
                    "[scheduler] Task %s refused: %s", task_id, exc.code
                )
                task_run.status = "error"
                task_run.error = exc.code
                current_output = dict(task_run.output or {})
                current_output["status"] = "error"
                current_output["task_error"] = exc.code
                current_output["agent_definition_refusal"] = exc.as_metadata()
                task_run.output = current_output
                admission_refused = True

            except ActionAdmissionError as exc:
                # Refused before any session or model dispatch; fixed code only.
                logger.error("[scheduler] Task %s refused: %s", task_id, exc.code)
                task_run.status = "error"
                task_run.error = exc.code
                current_output = dict(task_run.output or {})
                current_output["status"] = "error"
                current_output["task_error"] = exc.code
                current_output["action_admission_refusal"] = exc.as_metadata()
                task_run.output = current_output
                admission_refused = True

            except Exception as exc:
                failure = error_text("scheduled_task_failed", exc)
                logger.error("[scheduler] Task %s failed: %s", task_id, failure)
                task_run.status = "error"
                task_run.error = failure
                current_output = dict(task_run.output or {})
                current_output["status"] = "error"
                current_output["task_error"] = failure
                # A content refusal that reached the scheduler as its exception is typed by its class.
                if turn_error_class(exc) == TURN_ERROR_CONTENT_BLOCKED:
                    task_run.error = CONTENT_BLOCKED
                    current_output["task_error"] = CONTENT_BLOCKED
                    current_output["turn_outcome"] = {"state": "failed", "reason": CONTENT_BLOCKED}
                    content_blocked = True
                task_run.output = current_output

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

            if task_run.status == "error":
                failure_message = task_run.error or str((task_run.output or {}).get("task_error") or "task_failed")
                failed_entry, failure_decision = await escalate_failed_task_run_decision(
                    db,
                    task_id=task.id,
                    task_run_id=task_run.id,
                    error=failure_message,
                    trigger_id=trigger_id if trigger_type == "retry" else None,
                    admission_refused=admission_refused,
                    reply_contract_violation=reply_contract_violation,
                    runtime_stopped=runtime_stopped,
                    content_blocked=content_blocked,
                )
                failure_payload = failure_decision.as_dict()
                current_output = dict(task_run.output or {})
                current_output["failure_decision"] = failure_payload
                task_run.output = current_output
                if queue_entry:
                    queue_entry.status = failure_decision.queue_status
                    queue_entry.next_retry_at = failed_entry.next_retry_at
                    queue_entry.last_error = failure_decision.failure_message
                await db.commit()
                retry_scheduled = bool(
                    failure_decision.retryable and failure_decision.retry_delay_seconds is not None
                )
                if action_run_id:
                    # The run this turn ran in does not stay ``running`` silently; a retry continues it.
                    from ...services.workflow_runs.automation import pause_failed_action_run

                    try:
                        paused = await pause_failed_action_run(
                            db, action_run_id, content_blocked=content_blocked,
                            code=task_run.error or failure_message, task_run=task_run,
                            retry_scheduled=retry_scheduled,
                        )
                        if paused is not None:
                            task_run.output = {
                                **dict(task_run.output or {}),
                                "workflow_run": {"run_id": paused.id, "status": paused.status,
                                                 "pause_reason": paused.pause_reason},
                            }
                        await db.commit()
                    except Exception:
                        logger.exception("[scheduler] Task %s could not pause its workflow run %s",
                                         task_id, action_run_id)
                        await db.rollback()
                if retry_scheduled:
                    scheduler._schedule_failed_task_retry(
                        task_id=task.id,
                        failed_task_run_id=failed_entry.id,
                        delay_seconds=failure_decision.retry_delay_seconds,
                        # An alert-started run is retried as the same automation identity with the same alert.
                        **alert_retry_identity(task_run),
                    )

            # A test alert's run posts nothing.
            delivery_result = (
                None if suppress_delivery(task_run) else await _deliver_task_output_channel(db, task, task_run)
            )
            await finalize_alert_event(db, task_run, delivery_result)
            if delivery_result is not None:
                current_output = dict(task_run.output or {})
                current_output["channel_delivery"] = delivery_result
                task_run.output = current_output
                await db.commit()

            # The enqueue below is a single DB insert into the outbound-webhook
            # delivery queue (OutboundWebhookDelivery); a separate worker drains
            # that queue with its own bounded retry / dead-letter policy. So a
            # local retry here would be pointless. An enqueue failure is recorded
            # on the task_run.output trail and in a structured log instead of a
            # second queue.
            # A test alert's run posts nothing anywhere, outbound webhooks included.
            if not suppress_delivery(task_run):
                webhook_event_type = "task.failed" if task_run.status == "error" else "task.completed"
                try:
                    await emit_outbound_webhook_event(
                        db,
                        event_type=webhook_event_type,
                        project_id=task.project_id,
                        payload={
                            "task_id": task.id,
                            "task_name": task.name,
                            "task_run_id": task_run.id,
                            "status": task_run.status,
                            "trigger_type": trigger_type,
                            "session_id": task_run.session_id,
                            "error": task_run.error,
                            "output": task_run.output if isinstance(task_run.output, dict) else {},
                        },
                    )
                    await db.commit()
                except Exception as webhook_exc:
                    # Do NOT swallow: record the enqueue failure on the task_run so it
                    # is queryable, and log it with structure. The task_run itself
                    # stays finalized deterministically (success/error unchanged).
                    logger.exception(
                        "scheduler.task_webhook.enqueue_failed task_run_id=%s event_type=%s error=%s",
                        task_run.id,
                        webhook_event_type,
                        str(webhook_exc),
                    )
                    await db.rollback()
                    refreshed = (
                        await db.execute(select(TaskRun).where(TaskRun.id == task_run.id))
                    ).scalar_one_or_none()
                    if refreshed is not None:
                        task_run = refreshed
                    current_output = dict(task_run.output or {})
                    current_output["webhook_enqueue"] = {
                        "status": "failed",
                        "event_type": webhook_event_type,
                        "error": str(webhook_exc),
                        "failed_at": utc_now().isoformat(),
                    }
                    task_run.output = current_output
                    await db.commit()

            from ...services.workflow_runs.automation import action_run_config

            await scheduler._finalize_task_session_tree(
                db,
                task_run.session_id,
                preserve_phase_root=action_run_config(task) is not None,
                status="error" if task_run.status == "error" else "completed",
                stop_reason="task_failed" if task_run.status == "error" else "task_completed",
            )

            logger.info(
                "[scheduler] Task %s (%s) completed: %s",
                task_id,
                task.name,
                task_run.status,
            )
        finally:
            scheduler._active_task_ids.discard(task_id)
            scheduler._running_futures.pop(task_id, None)
            running_runs = getattr(scheduler, "_running_task_run_ids", None)
            if isinstance(running_runs, dict):
                running_runs.pop(task_id, None)
