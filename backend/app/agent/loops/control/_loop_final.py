"""Final fallback message handling for the standard loop."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from ....models import Message, TurnTrace
from ...core.runtime.turn_execution_binding import bound_turn_started_at

# Raw-output keys the loop sets when it judged a response non-final. The
# fallback trusts these explicit marks instead of re-guessing finality from
# prose ("i will", "let me", ...) — the loop already recorded WHY it
# suppressed each candidate.
_NON_FINAL_FLAG_PREFIXES = ("suppressed_", "stalled_")


def _usable_fallback_candidate(raw_output: dict) -> str:
    text = str(raw_output.get("content") or "").strip()
    if len(text) < 80:
        return ""
    for key, value in raw_output.items():
        if str(key).startswith(_NON_FINAL_FLAG_PREFIXES) and value:
            return ""
    return text


async def _latest_suppressed_final_candidate(*, db, session_id: str, turn_started_at: datetime) -> str:
    traces = (
        (
            await db.execute(
                select(TurnTrace)
                .where(TurnTrace.session_id == session_id, TurnTrace.created_at >= turn_started_at)
                .order_by(TurnTrace.created_at.desc(), TurnTrace.id.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    for trace in traces:
        raw_output = trace.raw_output if isinstance(trace.raw_output, dict) else {}
        candidate = _usable_fallback_candidate(raw_output)
        if candidate:
            return candidate
    return ""


async def emit_loop_final_fallback(
    *,
    db,
    session_id: str,
    request_messages: list[dict[str, str]],
    total_tokens_in: int,
    total_tokens_out: int,
    event_factory,
    _build_runtime_error_salvage_message,
) -> object:
    # Only rows this turn produced may become its answer; without a bound turn
    # there is no boundary, so nothing is salvaged.
    turn_started_at = bound_turn_started_at(session_id)
    final_content = ""
    if turn_started_at is not None:
        final_content = await _latest_suppressed_final_candidate(
            db=db, session_id=session_id, turn_started_at=turn_started_at
        ) or await _build_runtime_error_salvage_message(
            db=db,
            session_id=session_id,
            request_messages=request_messages,
            turn_started_at=turn_started_at,
        )
    if not final_content:
        # never end silently at the limit; say so and how to go on.
        final_content = (
            "I stopped at this step's tool call limit before finishing (the last calls repeated or made no "
            "progress, or the budget ceiling was reached). What is done so far stays done. Reply \"continue\" and I "
            "pick up where I stopped, or tell me what to change. "
            "[Agent reached maximum tool call iterations]"
        )
    msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=final_content,
        tokens_in=0,
        tokens_out=0,
    )
    db.add(msg)
    await db.commit()
    return event_factory(
        role="assistant",
        content=final_content,
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
    )
