"""What a task run does: its steps, a Work source's intake, or one agent turn and its verdict."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.services.session.reply_contract import REASON_PATH_UNSUPPORTED, declares_checked_reply

from ...services.content_security.refusal import TURN_ERROR_CONTENT_BLOCKED
from ...services.session.turn_final_outcome import (
    action_reply_verdict,
    action_stop_verdict,
    capture_trace_boundary,
    load_run_final_outcome,
    load_run_turn_error_class,
)
from ..tickets import (
    build_task_session_metadata as _build_task_session_metadata,
)
from ..tickets import (
    detect_agent_failure as _detect_agent_failure,
)
from .action_admission import admit_agent_turn
from .inbound_alert_turn import (
    alert_prompt,
    alert_session_metadata,
    inbound_alert_of,
)

logger = logging.getLogger(__name__)


#: The closed error code of an Action run whose turn a content policy refused (terminal).
CONTENT_BLOCKED = "content_blocked"


@dataclass
class _Outcome:
    # Set only by typed provenance (refusal handlers, the checked-reply verdict, the recorded runtime stop, the
    # turn's content-refusal class), never by error text; each makes the failure terminal.
    admission_refused: bool = False
    reply_contract_violation: bool = False
    runtime_stopped: bool = False
    content_blocked: bool = False
    # The workflow run this attempt's Action turn runs in (started or continued), if any.
    action_run_id: str | None = None


async def _run_steps(db, scheduler, task, task_run, outcome: _Outcome, *, trigger_type: str) -> None:
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

    final_context = await StepExecutor(scheduler).execute(db, task, task_run)
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
    task_run.status = "error" if any(s == "error" for s in step_statuses) else "success"
    # A step refused because its agent's reply format cannot be checked there is
    # terminal like an admission refusal; other step refusals keep their retries.
    if any(sr.error == REASON_PATH_UNSUPPORTED for sr in final_context["steps"].values()):
        task_run.error = REASON_PATH_UNSUPPORTED
        outcome.admission_refused = True


async def _run_intake(db, task, task_run) -> None:
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


async def _turn_setup(db, task, task_run, *, trigger_type: str) -> tuple[Any, str, dict, Any, Any]:
    from ...services.agent_definition_execution_outcomes import payload_resolution_metadata

    # Type, raw values, owner-visible agent, its Workspace and a real
    # instruction are admitted before any session or model dispatch (typed refusals).
    admitted = await admit_agent_turn(db, task)
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
    session_metadata.update(payload_resolution_metadata(admitted.agent_definition))
    coding_run = None
    if admitted.agent_definition:
        from ...services.secure_work.coding_run import ensure_coding_run_work_item

        coding_run = await ensure_coding_run_work_item(
            db,
            task=task,
            task_run=task_run,
            agent_definition=admitted.agent_definition,
            prompt=prompt,
            trigger_type=trigger_type,
        )
        if coding_run:
            session_metadata["coding_run_work_item_id"] = coding_run["work_item_id"]
            session_metadata["coding_run"] = coding_run
    return admitted, prompt, session_metadata, inbound_alert, coding_run


async def _run_agent_turn(db, scheduler, task, task_run, outcome: _Outcome, *, trigger_type: str) -> None:
    admitted, prompt, session_metadata, inbound_alert, coding_run = await _turn_setup(
        db, task, task_run, trigger_type=trigger_type)
    boundary: list[Any] = []

    async def _session_ready(ready_session):
        # Every agent run's traces are the ones after this boundary, taken right
        # before ``run_agent``; the session's history is never changed.
        boundary.append(await capture_trace_boundary(db, ready_session.id))
        # An Action naming a phased workflow runs its turn as the run's first phase.
        from ...services.workflow_runs.automation import start_action_run

        action_run = await start_action_run(db, task=task, task_run=task_run, session=ready_session,
                                            alert=inbound_alert)
        outcome.action_run_id = action_run.id if action_run is not None else None
        return await scheduler._assign_task_run_session(db, task_run, ready_session.id)

    session, result_payload = await scheduler._run_agent_for_task(
        db,
        task,
        prompt,
        agent_definition=admitted.agent_definition,
        runtime_target_id=admitted.runtime_target_id,
        thinking_level=admitted.thinking_level,
        session_metadata=session_metadata,
        on_session_ready=_session_ready,
        max_iterations=dict(task.config or {}).get("max_iterations"),
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
    await _judge_turn(db, task_run, outcome, session.id, boundary[-1] if boundary else None, result_payload,
                      checked_reply=declares_checked_reply(admitted.agent_definition))


async def _judge_turn(db, task_run, outcome: _Outcome, session_id: str, boundary, result_payload, *,
                      checked_reply: bool) -> None:
    # A content-policy refusal is a permanent refusal of the turn's content (typed trace class).
    turn_error = await load_run_turn_error_class(db, session_id, boundary) if boundary is not None else None
    if turn_error == TURN_ERROR_CONTENT_BLOCKED:
        task_run.output = {**task_run.output, "turn_outcome": {"state": "failed", "reason": CONTENT_BLOCKED}}
        task_run.status = "error"
        task_run.error = CONTENT_BLOCKED
        outcome.content_blocked = True
        return
    final = await load_run_final_outcome(db, session_id, boundary) if boundary is not None else None
    if checked_reply:
        # A checked agent succeeds only on its run's single finished, satisfied final.
        reply_failure = action_reply_verdict(final)
        task_run.output = {**task_run.output, "reply_contract": final.reply_contract if final else None}
        task_run.status = "error" if reply_failure else "success"
        task_run.error = reply_failure
        outcome.reply_contract_violation = reply_failure is not None
        return
    # A run whose own final trace recorded an explicit runtime stop fails with that
    # closed reason; every other outcome keeps the text-based rule unchanged.
    stop_reason = action_stop_verdict(final)
    if stop_reason is not None:
        task_run.output = {**task_run.output, "turn_outcome": {"state": "stopped", "reason": stop_reason}}
        task_run.status = "error"
        task_run.error = stop_reason
        outcome.runtime_stopped = True
    else:
        task_run.status = "error" if _detect_agent_failure(result_payload) else "success"
