"""Device turns as runs.

A device turn runs Claude Code on the user's machine. When the turn ends (finished, rejected by the device, or
failed), one ``turn_traces`` row records it for Observability → Runs: outcome, model, usage and cost as the device
reported them, and the start (the thread's newest user prompt). The row holds no content: the answer text is already
the thread's assistant message.

A turn that sends its model calls through the platform's gateway registers a fresh launcher key for that turn
(``POST /agent-gateway/sessions/register`` with the job id). ``stamp_gateway_session`` writes the job and the job's
current turn onto that gateway session, so the trace view can list the turn's calls; the Claude Code session id is
not enough, because a resumed turn keeps the old id but sends its calls under the new key.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, DeviceJobEvent, Message, TurnTrace
from ...models import Session as AgentSession
from ...time_utils import utc_now
from ..observability.run_summary import device_run_key, run_summary_fields, summary_row

DEVICE_PROVIDER = "device"
# A gateway session's device job and turn (metadata keys, set at the launcher's registration for that turn).
GATEWAY_JOB_KEY = "device_job_id"
GATEWAY_TURN_KEY = "device_turn_id"
# The idempotency key of a device turn's answer row: marks it as the device's and names its job and turn.
DEVICE_ANSWER_KEY = "device_job:"
# The device's own Claude Code subscription pays for the turn (like a gateway seat).
DEVICE_COST_STATUS = "not_billed_to_platform"
_STATUS_BY_EVENT = {"job_rejected": "blocked", "job_failed": "failed"}
# Ids per DELETE: asyncpg refuses more than 32767 bind parameters in one statement. A long Gemma turn can stream
# 33'788 chunks; one big DELETE would fail, the device's event would never be acknowledged and the channel would
# reconnect in a loop.
DELETE_BATCH = 5000


def device_answer_key(job: DeviceJob) -> str:
    return f"{DEVICE_ANSWER_KEY}{job.id}:{job.turn_id or ''}"[:100]


async def stamp_gateway_session(db: AsyncSession, session: AgentSession, job_id: str, user_id: str) -> None:
    """Mark a launcher's gateway session as the one of this job's current turn (the caller's own job only)."""
    if not job_id:
        return
    turn_id = (await db.execute(select(DeviceJob.turn_id).where(
        DeviceJob.id == job_id, DeviceJob.owner_user_id == user_id))).scalar_one_or_none()
    if not turn_id:
        return
    session.metadata_ = {**dict(session.metadata_ or {}), GATEWAY_JOB_KEY: job_id, GATEWAY_TURN_KEY: turn_id}


async def record_device_turn(db: AsyncSession, job: DeviceJob, message_type: str, body: dict[str, Any]) -> None:
    reported = str(body.get("status") or "")
    status = _STATUS_BY_EVENT.get(message_type) or ("failed" if reported and reported != "success" else "")
    reason = str(body.get("reason") or body.get("error") or "")[:80]
    started_at = (await db.execute(
        select(func.max(Message.created_at)).where(Message.session_id == job.session_id, Message.role == "user")
    )).scalar_one_or_none()
    raw_output = {"status": status, "reason": reason, "device_status": reported, "turn": job.turn_count}
    usage = dict(body["usage"]) if isinstance(body.get("usage"), dict) else {}
    cost = body.get("cost_usd")
    usage.update({"device_cost_usd": cost if isinstance(cost, (int, float)) else None,
                  "cost_status": DEVICE_COST_STATUS})
    # The turn's answer (written just before when the device sent a text) gets this row as its trace, so the chat
    # can open it; the row holds no prompt (the calls are listed from the turn's gateway session, if any).
    await db.flush()
    answer_id = (await db.execute(select(Message.id).where(
        Message.session_id == job.session_id, Message.idempotency_key == device_answer_key(job)).limit(1)
    )).scalar_one_or_none()
    trace = TurnTrace(
        id=str(uuid.uuid4()),
        session_id=job.session_id,
        message_id=answer_id,
        provider=DEVICE_PROVIDER,
        model=(job.model or job.turn_model or "")[:100],
        input_messages_json=[],
        context_snapshot_json={"source": "device", "job_id": job.id, "turn_id": job.turn_id, "profile": job.profile},
        tool_trace_json=[],
        raw_output=raw_output,
        usage_json=usage,
        created_at=utc_now(),
    )
    db.add(trace)
    db.add(summary_row(trace, run_summary_fields(
        run_key=device_run_key(job.id, job.turn_id),
        raw_output=raw_output,
        started_at=started_at,
        label=f"Claude Code on device ({job.profile})",
    )))


async def compact_finished_turn_text(db: AsyncSession, job: DeviceJob) -> int:
    """Drop the streamed ``text_delta`` chunks of a finished turn: its ``text`` events carry the full text.

    The chat merges deltas while the turn streams and displays the final text afterward, so nothing visible is lost.
    """
    if not job.turn_id:
        return 0
    rows = (await db.execute(select(DeviceJobEvent.id, DeviceJobEvent.body).where(
        DeviceJobEvent.job_id == job.id, DeviceJobEvent.type == "job_event"))).all()
    finished_text = any(isinstance(body, dict) and body.get("turn_id") == job.turn_id and body.get("kind") == "text"
                        for _id, body in rows)
    chunks = [event_id for event_id, body in rows if isinstance(body, dict) and body.get("turn_id") == job.turn_id
              and body.get("kind") == "text_delta"]
    if not finished_text or not chunks:
        return 0
    for start in range(0, len(chunks), DELETE_BATCH):
        await db.execute(delete(DeviceJobEvent).where(DeviceJobEvent.id.in_(chunks[start:start + DELETE_BATCH])))
    return len(chunks)

