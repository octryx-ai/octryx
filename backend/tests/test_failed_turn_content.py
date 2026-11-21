"""A failed turn never presents content it did not produce.

A provider failure in turn 2 must not persist turn 1's
answer: the runtime-failure branch must not salvage the latest earlier assistant message of
the whole history. Salvage reads only rows persisted since the turn was admitted.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agent.core.runtime.turn_execution_binding import (
    bind_turn_execution_snapshot,
    bound_turn_started_at,
    clear_turn_execution_snapshot,
)
from app.agent.loops.response._loop_runtime_salvage import _build_runtime_error_salvage_message
from app.models import Message, ToolCall, TurnTrace
from app.models.runtime.product_run import ProductRun, ProductRunAttempt
from app.time_utils import utc_now
from tests import product_run_chat_support
from tests.product_run_chat_binding_support import TRANSIENT, _drain, _session, _turn

# The scripted provider world of the binding tests (no network, call counter).
world = product_run_chat_support.world

# Long enough, and final-sounding enough, that a salvage heuristic would accept it.
EARLIER_ANSWER = (
    "The quarterly figures are complete: revenue grew by twelve percent, costs stayed flat, "
    "and the forecast for the next quarter is unchanged."
)
EARLIER_RESPONSE = {
    "content": EARLIER_ANSWER,
    "tool_calls": None,
    "usage": {"prompt_tokens": 5, "completion_tokens": 9},
}


async def _latest_attempt(db, session_id: str) -> ProductRunAttempt:
    return (
        await db.execute(
            select(ProductRunAttempt)
            .join(ProductRun, ProductRun.id == ProductRunAttempt.run_id)
            .where(ProductRun.session_id == session_id)
            .order_by(ProductRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_a_provider_failure_after_a_successful_turn_shows_the_failure_not_the_earlier_answer(
    db, monkeypatch, world
) -> None:
    session = await _session(db)
    world["script"] = [EARLIER_RESPONSE]
    await _drain(_turn(db, session))
    assert (await _latest_attempt(db, session.id)).state == "finished_unverified"

    world["script"] = [TRANSIENT, TRANSIENT]
    events = await _drain(_turn(db, session))

    assert world["script"] == []
    assert events[-1].content.startswith("Agent error:")
    assert EARLIER_ANSWER not in events[-1].content
    latest = (
        await db.execute(
            select(Message)
            .where(Message.session_id == session.id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    assert latest.content == events[-1].content
    failure_trace = (
        await db.execute(
            select(TurnTrace).where(TurnTrace.session_id == session.id, TurnTrace.provider == "runtime-fallback")
        )
    ).scalar_one()
    # The earlier answer was in the request history, so it was there to be (wrongly) salvaged.
    assert EARLIER_ANSWER in str(failure_trace.input_messages_json)
    attempt = await _latest_attempt(db, session.id)
    assert (attempt.state, attempt.end_reason) == ("failed", "provider_error")


@pytest.mark.asyncio
async def test_runtime_salvage_reads_only_rows_persisted_since_the_turn_started(db) -> None:
    session = await _session(db)
    before = utc_now() - timedelta(seconds=5)
    earlier_turn_trace = TurnTrace(
        session_id=session.id, provider="stub", model="stub", raw_output={"content": EARLIER_ANSWER}, created_at=before
    )
    earlier_turn_diagram = ToolCall(
        session_id=session.id,
        tool_name="create_diagram",
        parameters={},
        result={"diagram_id": "diagram-from-an-earlier-turn", "title": "Earlier"},
        status="success",
        created_at=before,
    )
    db.add_all([earlier_turn_trace, earlier_turn_diagram])
    await db.commit()

    bind_turn_execution_snapshot(session.id, {})
    try:
        turn_started_at = bound_turn_started_at(session.id)
        assert turn_started_at is not None and turn_started_at > before
        salvaged = await _build_runtime_error_salvage_message(
            db=db,
            session_id=session.id,
            request_messages=[{"role": "user", "content": "And the next quarter?"}],
            turn_started_at=turn_started_at,
        )
        assert salvaged == ""

        # The same kind of row, produced by this turn, is still this turn's evidence.
        db.add(
            ToolCall(
                session_id=session.id,
                tool_name="create_diagram",
                parameters={},
                result={"diagram_id": "diagram-from-this-turn", "title": "Now"},
                status="success",
            )
        )
        await db.commit()
        salvaged = await _build_runtime_error_salvage_message(
            db=db,
            session_id=session.id,
            request_messages=[{"role": "user", "content": "And the next quarter?"}],
            turn_started_at=turn_started_at,
        )
    finally:
        clear_turn_execution_snapshot(session.id)
    assert "diagram://diagram-from-this-turn" in salvaged
    assert "diagram-from-an-earlier-turn" not in salvaged


def test_no_bound_turn_has_no_start() -> None:
    assert bound_turn_started_at("session-without-a-bound-turn") is None
