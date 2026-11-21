"""Settle a chat turn that was cancelled or raised, for every entry path.

The counterpart of ``turn_settlement`` for a turn whose agent stream did not end
normally. Both functions open their own database session from ``session_factory``
(the turn's session is discarded by then), clear the turn marker, persist an explicit
run state, commit and publish the ``run_state`` stream event:

* :func:`settle_cancelled_turn`: ``stopped`` / ``user_cancelled`` with the fixed
  "Generation stopped by user." message;
* :func:`settle_failed_turn`: the recovery cases below, else ``failed`` / ``error``
  with the fixed "Agent error: ..." message (error code and type only, never the
  exception text).

Recovery of a late exception (first match wins):

1. a sub-agent resume with no answer after the latest user message: the latest usable
   trace content becomes the answer, ``completed``;
2. an answer after the latest user message, or a sub-agent resume with any answer:
   ``completed`` / ``stopped`` from that answer;
3. the run state was already settled ``completed`` (the exception came after it).

The caller decides what the exception does next: the background runner ends the task,
``/api/v1`` re-raises it so its HTTP contract is unchanged.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, TurnTrace
from ...models import Session as AgentSession
from ..error_facts import error_text
from .run_state import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_STOPPED,
    get_session_run_completion_reason,
    get_session_run_status,
    infer_completion_reason_from_content,
    set_session_run_state,
)
from .stream import session_stream_manager
from .turn_approval_state import end_chat_turn
from .turn_event_payloads import run_state_payload

logger = logging.getLogger(__name__)

# Statuses a failed or cancelled turn never overwrites (it keeps waiting or stays archived).
_KEPT_STATUSES = frozenset({"archived", "pending_approval", "awaiting_subagents"})
_STOPPED_CONTENT = "Generation stopped by user."
_SUB_AGENT_GROUP_KEYS = (
    "current_sub_agent_group_id",
    "sub_agent_group_child_session_ids",
    "sub_agent_resume_started_group_id",
)


def latest_non_error_assistant_message(messages: list[Message]) -> Message | None:
    for message in reversed(messages):
        if str(message.role or "").strip() != "assistant":
            continue
        content = str(message.content or "").strip()
        if not content or content.startswith("Agent error:"):
            continue
        return message
    return None


def _usable_trace_recovery_content(value: object) -> str:
    content = str(value or "").strip()
    if not content:
        return ""
    lowered = content.lower()
    if lowered.startswith("agent error:") or lowered.startswith("agent stopped because"):
        return ""
    if lowered.startswith(("i will ", "i'll ", "let me ", "next ", "now i ")):
        return ""
    return content


async def _latest_trace_recovery_content(db: AsyncSession, *, session_id: str) -> str:
    traces = (
        (
            await db.execute(
                select(TurnTrace)
                .where(TurnTrace.session_id == session_id)
                .order_by(TurnTrace.created_at.desc(), TurnTrace.id.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    for trace in traces:
        raw_output = trace.raw_output if isinstance(trace.raw_output, dict) else {}
        content = _usable_trace_recovery_content(raw_output.get("content"))
        if content:
            return content
    return ""


def _end_turn(session: AgentSession, *, extra_keys: tuple[str, ...] = ()) -> None:
    metadata = dict(session.metadata_ or {})
    end_chat_turn(metadata)
    metadata.pop("resume_state", None)
    for key in extra_keys:
        metadata.pop(key, None)
    session.metadata_ = metadata


async def _publish_run_state(session_id: str, **payload) -> None:
    await session_stream_manager.publish(session_id, "run_state", run_state_payload(**payload))


async def settle_cancelled_turn(*, session_factory, session_id: str) -> None:
    async with session_factory() as db:
        db.add(Message(id=str(uuid.uuid4()), session_id=session_id, role="assistant", content=_STOPPED_CONTENT))
        session = await db.get(AgentSession, session_id)
        if session:
            if session.status not in _KEPT_STATUSES:
                session.status = "active"
            _end_turn(session, extra_keys=("run_started_at",))
            set_session_run_state(session, RUN_STATUS_STOPPED, "user_cancelled")
        await db.commit()
    await _publish_run_state(session_id, run_status=RUN_STATUS_STOPPED, run_completion_reason="user_cancelled")


def _is_sub_agent_resume(session: AgentSession | None, prompt: str) -> bool:
    metadata = dict(session.metadata_ or {}) if session else {}
    lowered = str(prompt or "").lower()
    return bool(
        str(metadata.get("sub_agent_resume_started_group_id") or "").strip()
        or "sub-agents" in lowered
        or "sub agent" in lowered
    )


def _answered_after_latest_user(messages: list[Message], answer: Message | None) -> bool:
    if answer is None:
        return False
    latest_user = next((message for message in reversed(messages) if str(message.role or "").strip() == "user"), None)
    if latest_user is None:
        return True
    return bool(answer.created_at and latest_user.created_at and answer.created_at >= latest_user.created_at)


async def settle_failed_turn(*, session_factory, session_id: str, prompt: str, exc: BaseException) -> None:
    async with session_factory() as db:
        session = await db.get(AgentSession, session_id)
        history = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        messages = list((await db.execute(history)).scalars().all())
        answer = latest_non_error_assistant_message(messages)
        answered = _answered_after_latest_user(messages, answer)
        sub_agent_resume = _is_sub_agent_resume(session, prompt)

        if sub_agent_resume and not answered:
            recovered = await _latest_trace_recovery_content(db, session_id=session_id)
            if recovered:
                db.add(Message(id=str(uuid.uuid4()), session_id=session_id, role="assistant", content=recovered))
                if session:
                    session.status = "active" if session.status != "archived" else session.status
                    _end_turn(session, extra_keys=_SUB_AGENT_GROUP_KEYS)
                    set_session_run_state(session, RUN_STATUS_COMPLETED, "completed")
                await db.commit()
                await _publish_run_state(
                    session_id,
                    run_status=RUN_STATUS_COMPLETED,
                    run_completion_reason="completed",
                    recovered_from_late_exception=True,
                )
                return

        if answered or (sub_agent_resume and answer is not None and str(answer.content or "").strip()):
            reason = infer_completion_reason_from_content(answer.content if answer else "")
            run_status = RUN_STATUS_STOPPED if reason == "agent_stopped" else RUN_STATUS_COMPLETED
            if session:
                if session.status not in _KEPT_STATUSES | {"active"}:
                    session.status = "active"
                _end_turn(session)
                set_session_run_state(session, run_status, reason)
            await db.commit()
            await _publish_run_state(
                session_id, run_status=run_status, run_completion_reason=reason, recovered_from_late_exception=True
            )
            return

        if session and get_session_run_status(session) == RUN_STATUS_COMPLETED:
            reason = get_session_run_completion_reason(session) or infer_completion_reason_from_content(
                answer.content if answer else ""
            )
            await db.commit()
            await _publish_run_state(
                session_id,
                run_status=RUN_STATUS_COMPLETED,
                run_completion_reason=reason,
                recovered_from_late_exception=True,
            )
            return

        failure = error_text("agent_run_failed", exc)
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=f"Agent error: the agent run failed ({failure}).",
            )
        )
        if session:
            if session.status not in _KEPT_STATUSES:
                session.status = "active"
            _end_turn(session)
            set_session_run_state(session, RUN_STATUS_FAILED, "error")
        await db.commit()
    await _publish_run_state(session_id, run_status=RUN_STATUS_FAILED, run_completion_reason="error", error=failure)


__all__ = ["latest_non_error_assistant_message", "settle_cancelled_turn", "settle_failed_turn"]
