"""A final answer built on this turn's tool evidence cites it with openable links (evidence enforcement).

Without it a plain chat turn can answer code questions from ``web_search`` / ``web_fetch`` with zero links,
and partly wrong against the fetched file.

This guard runs where the final answer is accepted, after the other response guards (the inline
pseudo-tool-call guard included) let it through, for user-facing answering turns only (a
sub-agent's answer is a tool result of its parent, whose own answer is checked; see
``answer_evidence.decision.ENFORCED_CAPABILITY_TYPES`` for the mode-of-work scope). It follows the
pseudo-tool-call guard's pattern:

The decision is proportionate: a reply that falls short is delivered with its uncited
claims marked (``mark``); the reminder and refusal below stay for traces and callers that drive them explicitly.

- the reply passes ``check_answer_evidence`` (``services/answer_evidence``): it is accepted, and the
  trace records ``passed`` (or ``unsourced`` when the turn carries no openable source at all);
- it fails for the first time: it is suppressed, the model gets the one reminder, the trace records
  ``reminded``;
- it fails again after the reminder: the turn ends in the explicit refusal
  (``raw_output.refusal_reason`` ``answer_evidence_uncited`` / ``answer_evidence_invented_url``) with
  the sources the turn found; the uncited text is never delivered. That refusal is the turn's final
  trace and records an explicit runtime stop with the matching closed reason, so the turn
  reads ``stopped``, never ``finished``, ``completed`` or ``unknown``. The reminder stays intermediate.

The reminder is counted in the turn's own messages by its fixed marker, so "one reminder" holds across
the loop's iterations, including when the model gathers more evidence after the reminder.

A run phase turn is guarded the same way; when this guard ends it, ``_loop_response_guards`` still records the
turn's workflow checks (``record_checks_for_ended_turn``), so the run gets its phase result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....services.answer_evidence.check import REFUSAL_REASON_INVENTED_URL, REFUSAL_REASON_UNCITED
from ....services.answer_evidence.decision import (
    ACTION_ACCEPT,
    ACTION_MARK,
    ACTION_REMIND,
    ACTION_SKIP,
    decide_answer_evidence,
)
from ....services.answer_evidence.record import ANSWER_EVIDENCE_KEY
from ....services.answer_evidence.texts import REMINDER_MARKER
from ....services.session.turn_execution_snapshot import (
    RUNTIME_STOP_ANSWER_EVIDENCE_INVENTED_URL,
    RUNTIME_STOP_ANSWER_EVIDENCE_UNCITED,
    with_runtime_stop,
)

# Closed: each final refusal reason has exactly one runtime stop reason; anything else records no stop.
_RUNTIME_STOP_BY_REFUSAL = {
    REFUSAL_REASON_UNCITED: RUNTIME_STOP_ANSWER_EVIDENCE_UNCITED,
    REFUSAL_REASON_INVENTED_URL: RUNTIME_STOP_ANSWER_EVIDENCE_INVENTED_URL,
}


def _latest_user_message(request_messages: list[dict[str, Any]]) -> str:
    for message in reversed(request_messages or []):
        if isinstance(message, dict) and str(message.get("role") or "") == "user":
            return str(message.get("content") or "")
    return ""


def evidence_reminder_count(messages: list[dict[str, Any]]) -> int:
    return sum(
        1
        for message in messages or []
        if isinstance(message, dict)
        and str(message.get("role") or "") == "system"
        and str(message.get("content") or "").startswith(REMINDER_MARKER)
    )


async def handle_answer_evidence_guard(
    *,
    db: Any,
    session_id: str,
    runtime: dict[str, Any],
    response: dict[str, Any],
    request_messages: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    runtime_attempts: list[dict[str, Any]],
    runtime_settings: dict[str, Any],
    usage_model: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    capability_type: str,
    has_followup_steps: bool,
    sub_agent_depth: int,
    turn_tool_history: list[dict[str, Any]],
    persist_turn_trace: Callable[..., Any],
    persist_traced_assistant_message: Callable[..., Any],
) -> dict[str, Any] | None:
    """Record the decision on ``context_snapshot``; ``None`` accepts the reply, ``{"action": "mark", "content"}``
    delivers the marked reply, else the loop outcome.

    Only a user-facing final answer of an answering turn is checked: a reply with tool calls, a step
    summary with steps still to run, a sub-agent's answer, and the delivery report of a ``change`` /
    ``admin`` turn pass through unrecorded.
    """
    if tool_calls or has_followup_steps:
        return None
    decision = decide_answer_evidence(
        content=content, turn_tool_history=turn_tool_history, user_message=_latest_user_message(request_messages),
        reminders=evidence_reminder_count(messages), capability_type=capability_type, sub_agent_depth=sub_agent_depth,
    )
    if decision.action == ACTION_SKIP:
        return None
    context_snapshot[ANSWER_EVIDENCE_KEY] = decision.record
    if decision.action == ACTION_ACCEPT:
        return None
    if decision.action == ACTION_MARK:
        # Delivered, with each uncited claim marked: the caller continues with this content.
        return {"action": ACTION_MARK, "content": decision.content}
    usage = response.get("usage", {})
    raw_output = {"content": content, "tool_calls": [], "runtime_attempts": runtime_attempts}
    if decision.action == ACTION_REMIND:
        messages.append({"role": "assistant", "content": content or ""})
        messages.append({"role": "system", "content": decision.reminder})
        await persist_turn_trace(
            db=db, session_id=session_id, message_id=None, provider=runtime["provider_name"], model=usage_model,
            input_messages=request_messages, context_snapshot=context_snapshot, tool_trace=[], usage=usage,
            raw_output={**raw_output, "suppressed_for_answer_evidence": True}, trace_limits=runtime_settings,
        )
        await db.commit()
        return {"action": "continue"}
    return await _persist_evidence_refusal(
        db=db, session_id=session_id, runtime=runtime, request_messages=request_messages,
        context_snapshot=context_snapshot, runtime_settings=runtime_settings, usage_model=usage_model,
        usage=usage, raw_output=raw_output, decision=decision,
        persist_traced_assistant_message=persist_traced_assistant_message,
    )


async def _persist_evidence_refusal(
    *,
    db: Any,
    session_id: str,
    runtime: dict[str, Any],
    request_messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    runtime_settings: dict[str, Any],
    usage_model: str,
    usage: dict[str, Any],
    raw_output: dict[str, Any],
    decision: Any,
    persist_traced_assistant_message: Callable[..., Any],
) -> dict[str, Any]:
    """End the turn in the explicit refusal, recorded as the runtime stop it is."""
    stop_reason = _RUNTIME_STOP_BY_REFUSAL.get(decision.refusal_reason)
    stop = {"runtime_stop_reason": stop_reason} if stop_reason else {}
    await persist_traced_assistant_message(
        db=db,
        session_id=session_id,
        content=decision.refusal,
        provider=runtime["provider_name"],
        model=usage_model,
        input_messages=request_messages,
        # The refusal is this turn's final trace: it records the stop it is (persistence marks the stored
        # trace from ``runtime_stop_reason``; the copy here states the same closed marker).
        context_snapshot=with_runtime_stop(context_snapshot, stop_reason) if stop_reason else context_snapshot,
        tool_trace=[],
        raw_output={**raw_output, "refusal_reason": decision.refusal_reason},
        usage=usage,
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        trace_limits=runtime_settings,
        **stop,
    )
    await db.commit()
    return {"action": "return", "yield_content": decision.refusal, "yield_model": usage_model}


__all__ = ["evidence_reminder_count", "handle_answer_evidence_guard"]
