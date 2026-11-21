"""Device events applied to their job, exactly once per ``seq`` (``devices.jobs``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, DeviceJobApproval, DeviceJobEvent, Message
from ...time_utils import utc_now
from .job_approvals import _approval_requested
from .job_state import (
    DEFAULT_APPROVAL_TIMEOUT_S,
    MAX_TEXT_CHARS,
    STATUS_FAILED,
    STATUS_IDLE,
    STATUS_REJECTED,
    STATUS_RUNNING,
    _audit,
    _clip,
    bounded_body,
    serialize_approval,
)
from .run_trace import compact_finished_turn_text, device_answer_key, record_device_turn
from .turn_cost import price_turn


def _reported_model(job: DeviceJob, body: dict[str, Any]) -> None:
    model = body.get("model")
    if isinstance(model, str) and model.strip() and model.isprintable():
        job.model = model.strip()[:200]


async def _turn_finished(db: AsyncSession, job: DeviceJob, body: dict[str, Any]) -> None:
    job.status, job.turn_state, job.stop_state = STATUS_IDLE, "done", None
    outcome = str(body.get("status") or "")
    # A fixed code from the device wins over the bare outcome (``service_restarted``, ``claude_initialize_timeout``).
    detail = str(body.get("reason") or body.get("error") or "")[:80]
    job.status_reason = (detail or outcome) if outcome and outcome != "success" else None
    if body.get("claude_session_id"):
        job.claude_session_id = str(body["claude_session_id"])[:80]
    _reported_model(job, body)
    cost = body.get("cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        job.cost_usd = float(job.cost_usd or 0) + float(cost)
    if isinstance(body.get("usage"), dict):
        job.usage = body["usage"]
    text = _clip(str(body.get("result_text") or ""), MAX_TEXT_CHARS)
    if text:
        # The model the device reported for this turn names the answer; the profile only when it reported none.
        # The key marks the answer as the device's (the chat reopens such a thread on its device).
        model = (job.model or job.turn_model or f"device:{job.profile}")[:100]
        answer = Message(session_id=job.session_id, role="assistant", content=text, model=model,
                         idempotency_key=device_answer_key(job))
        db.add(answer)
        await _bind_refusals(db, job, answer)


async def _bind_refusals(db: AsyncSession, job: DeviceJob, answer: Message) -> None:
    """The platform's refusals of this turn's tool calls belong to its answer (shown with the
    message's tool steps, not only in the trace): the device session's unbound ``denied_by_policy`` rows. The device
    session is the gateway session whose key is the job's Claude Code session."""
    from ...models import Session, ToolCall  # noqa: PLC0415
    from ..agent_gateway.contract import TOOL_CALL_STATUS_DENIED  # noqa: PLC0415

    if not job.claude_session_id:
        return
    gateway = (await db.execute(select(Session.id).where(
        Session.user_id == job.owner_user_id,
        Session.metadata_["gateway_session_key"].as_string() == job.claude_session_id,
    ).limit(1))).scalar_one_or_none()
    if gateway is None:
        return
    await db.flush()  # the answer's id
    rows = (await db.execute(select(ToolCall).where(
        ToolCall.session_id == gateway, ToolCall.status == TOOL_CALL_STATUS_DENIED,
        ToolCall.message_id.is_(None)).limit(500))).scalars().all()
    for row in rows:
        row.message_id = answer.id


async def _continue_run(db: AsyncSession, job: DeviceJob, *, failed: bool = False, said: str = "",
                        rejected: bool = False, seat_rate_limits: Any = None) -> None:
    """The run's next phase, left pending while this job's turn was busy; a failed phase turn pauses the run.
    ``said``: what the device's model answered on a failed turn (a usage limit names its reset), shown in the pause.
    ``rejected``: the device refused the turn before any agent started (``job_rejected``)."""
    from ..workflow_runs.octryx.continuation import continue_after_device_turn

    await db.flush()
    failure = (job.status_reason or "failed") if failed else None
    await continue_after_device_turn(db, job.session_id, failure=failure, said=said, rejected=rejected,
                                     seat_rate_limits=seat_rate_limits)
    from ..workflow_runs.teamwork.coordinator import main_turn_ended

    await main_turn_ended(db, job.session_id)  # a board wake of the coordinator that waited for this thread


async def _drop_held_prompt(db: AsyncSession, job: DeviceJob) -> None:
    from .deferred_turn_message import drop  # noqa: PLC0415

    await drop(db, job)


PIPELINE_DONE = "pipeline_done"  # octryx-claude device_session.PIPELINE_DONE
WORK_GIT_DONE = "work_git_done"  # octryx-claude device_session.WORK_GIT_DONE (teamwork: worktrees and merges)
LAUNCHER_STEPS_DONE = frozenset({PIPELINE_DONE, WORK_GIT_DONE})


async def _job_accepted(db: AsyncSession, job: DeviceJob) -> None:
    job.status, job.turn_state, job.disconnected_at = STATUS_RUNNING, "accepted", None
    from .deferred_turn_message import release  # noqa: PLC0415 - a continuation's prompt reaches the chat now

    await release(db, job)
    _audit(db, actor_id=job.owner_user_id, action="device.job.accepted", job=job, details={"turn": job.turn_count})


async def _launcher_steps_done(db: AsyncSession, job: DeviceJob, body: dict[str, Any]) -> None:
    # The launcher ran the run's CI pipeline (or its git work, ``teamwork``) for this turn: the job's work is
    # done, no agent turn followed (``workflow_runs.pipeline``); never a rejection or a failed phase turn.
    job.status, job.turn_state, job.status_reason = STATUS_IDLE, "done", None
    await _drop_held_prompt(db, job)  # green: no agent ran, its "fix it" prompt never reaches the chat
    _audit(db, actor_id=job.owner_user_id, action=f"device.job.{body['reason']}", job=job, details={})
    await _continue_run(db, job)


async def _job_rejected(db: AsyncSession, job: DeviceJob, message_type: str, body: dict[str, Any]) -> None:
    reason = str(body.get("reason") or "rejected_by_device")[:80]
    await _drop_held_prompt(db, job)  # no agent ran (hands_on_done too): the prompt stays out of the chat
    job.turn_state = "rejected"
    job.status = STATUS_REJECTED if not job.claude_session_id and job.turn_count <= 1 else STATUS_IDLE
    job.status_reason = reason
    _audit(db, actor_id=job.owner_user_id, action="device.job.rejected", job=job, details={"reason": reason})
    await record_device_turn(db, job, message_type, body)


async def _approval_request(db: AsyncSession, job: DeviceJob, body: dict[str, Any],
                            limits: dict[str, Any]) -> dict[str, Any]:
    approval = await _approval_requested(
        db, job, body, timeout_s=int(limits.get("approval_timeout_s") or DEFAULT_APPROVAL_TIMEOUT_S),
        allow_job_edits=bool(limits.get("allow_job_edit_scope", True)))
    if approval is None:
        return {}
    published = {"approval": serialize_approval(approval)}
    from ..attention.stream import nudge_after_commit
    from ..workflow_runs.octryx.approval_loop import approval_requested

    nudge_after_commit(db, job.owner_user_id, event="device_approval")

    await approval_requested(db, job)  # a phase turn asking again and again with nobody answering pauses
    return published


async def _turn_finished_event(db: AsyncSession, job: DeviceJob, message_type: str, body: dict[str, Any]) -> None:
    # The platform prices the turn's own usage; the device's cumulative figure is information only (``turn_cost``).
    reported_model = body.get("model") if isinstance(body.get("model"), str) else ""
    body = await price_turn(db, body, model=(reported_model or job.model or job.turn_model or "").strip())
    await _turn_finished(db, job, body)
    _audit(db, actor_id=job.owner_user_id, action="device.job.turn_finished", job=job,
           details={"status": str(body.get("status") or ""), "cost_usd": body.get("cost_usd")})
    await record_device_turn(db, job, message_type, body)
    await compact_finished_turn_text(db, job)
    await _continue_run(db, job, failed=str(body.get("status") or "") not in ("", "success"),
                        said=str(body.get("result_text") or ""), seat_rate_limits=body.get("seat_rate_limits"))


async def _job_event(db: AsyncSession, job: DeviceJob, body: dict[str, Any]) -> None:
    if body.get("kind") == "session" and body.get("claude_session_id"):
        job.claude_session_id = str(body["claude_session_id"])[:80]
        _reported_model(job, body)
    elif body.get("kind") in ("wip_pushed", "wip_failed"):
        from ..workflow_runs.wip import record_wip

        await record_wip(db, job, body)
    elif body.get("kind") == "token_profile":
        from ..observability.token_profile.metrics import observe as observe_tokens

        await observe_tokens(db, job, body)  # where the tokens go, counted at the event (no metric query)


async def _job_failed(db: AsyncSession, job: DeviceJob, message_type: str, body: dict[str, Any]) -> None:
    job.status, job.status_reason, job.finished_at = STATUS_FAILED, str(body.get("reason") or "")[:80], utc_now()
    _audit(db, actor_id=job.owner_user_id, action="device.job.failed", job=job,
           details={"reason": job.status_reason})
    await record_device_turn(db, job, message_type, body)


async def apply_event(db: AsyncSession, job: DeviceJob, message_type: str, body: dict[str, Any], *,
                      limits: dict[str, Any]) -> dict[str, Any]:
    """Apply one stored device event to the job; returns what the chat should see."""
    turn_matches = str(body.get("turn_id") or "") == (job.turn_id or "")
    published: dict[str, Any] = {}
    if message_type == "job_accepted" and turn_matches:
        await _job_accepted(db, job)
    elif message_type == "job_rejected" and turn_matches and body.get("reason") in LAUNCHER_STEPS_DONE:
        await _launcher_steps_done(db, job, body)
        await db.flush()
        return published
    elif message_type == "job_rejected" and turn_matches:
        await _job_rejected(db, job, message_type, body)
    elif message_type == "approval_request":
        published = await _approval_request(db, job, body, limits)
    elif message_type == "approval_resolved":
        await db.execute(update(DeviceJobApproval).where(
            DeviceJobApproval.job_id == job.id, DeviceJobApproval.request_id == str(body.get("approval_id") or ""),
            DeviceJobApproval.status == "pending").values(status="expired"))
    elif message_type == "turn_finished" and turn_matches:
        await _turn_finished_event(db, job, message_type, body)
    elif message_type == "job_event":
        await _job_event(db, job, body)
    elif message_type == "job_failed":
        await _job_failed(db, job, message_type, body)
    if message_type in ("job_rejected", "job_failed") and turn_matches:
        # A turn that ended otherwise hands over too; a refused one may be offered once more (``continuation``).
        await _continue_run(db, job, failed=True, rejected=message_type == "job_rejected")
    await db.flush()
    return published


async def store_event(db: AsyncSession, job: DeviceJob, seq: int, message_type: str,
                      body: dict[str, Any]) -> DeviceJobEvent:
    event = DeviceJobEvent(job_id=job.id, seq=seq, type=message_type[:40], body=bounded_body(body))
    db.add(event)
    job.last_event_seq = seq
    await db.flush()
    return event

