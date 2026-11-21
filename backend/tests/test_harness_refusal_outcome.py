"""An answer-guard refusal records the native loop's runtime outcome, never ``finished``.

The turn is the scripted one of ``test_evidence_runtime_paths``. An answer-evidence refusal is the turn's
explicit stop with the native loop's closed reason (``_loop_answer_evidence._RUNTIME_STOP_BY_REFUSAL``). A
pseudo-tool-call refusal has no closed stop reason, so it stays unmarked (``unknown``). An accepted answer still finishes. The delivered
content is unchanged.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import TurnTrace
from app.services.session.turn_execution_snapshot import RUNTIME_STOP_REASON_KEY, TURN_EXECUTION_SNAPSHOT_KEY
from app.services.session.turn_execution_summary import runtime_outcome_from_trace
from tests.evidence_runtime_support import _SCENARIO_OVERRIDES, _evidence_scenario  # noqa: F401 - autouse fixture
from tests.harness_runtime_support import fake_world  # noqa: F401 - fixture
from tests.test_evidence_runtime_paths import CITED, PSEUDO, UNCITED, _outcome, _run_turn, _sourced_tool
from tests.test_harness_runtime_parity import TOOL_RESPONSE


async def _final_outcome(db, session_id: str) -> tuple[str, str | None]:
    traces = (
        await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id).order_by(TurnTrace.created_at))
    ).scalars().all()
    final = [trace for trace in traces if trace.message_id is not None][-1]
    snapshot = final.context_snapshot_json.get(TURN_EXECUTION_SNAPSHOT_KEY) or {}
    return runtime_outcome_from_trace(final.context_snapshot_json, final.raw_output), snapshot.get(
        RUNTIME_STOP_REASON_KEY
    )


def _refusing_decision(monkeypatch) -> None:
    """The guard no longer refuses; a refusal decided elsewhere stays a recorded runtime stop.

    The real check and the real reminder/refusal texts; only the choice to refuse after the reminder is forced, on
    the native loop's decision import.
    """
    from app.agent.loops.response import _loop_answer_evidence
    from app.services.answer_evidence.check import (
        answer_evidence_record,
        check_answer_evidence,
        evidence_refusal,
        evidence_reminder,
    )
    from app.services.answer_evidence.decision import ACTION_REFUSE, ACTION_REMIND, EvidenceDecision
    from app.services.answer_evidence.evidence import collect_turn_evidence

    def decide(*, content, turn_tool_history, user_message, reminders, capability_type, sub_agent_depth):
        evidence = collect_turn_evidence(turn_tool_history)
        check = check_answer_evidence(content, evidence, user_message=user_message)
        if not reminders:
            record = answer_evidence_record("reminded", check, reminder_count=1)
            return EvidenceDecision(ACTION_REMIND, record, reminder=evidence_reminder(check))
        return EvidenceDecision(
            ACTION_REFUSE, answer_evidence_record("refused", check, reminder_count=reminders),
            refusal=evidence_refusal(check, evidence), refusal_reason=check.refusal_reason,
        )

    monkeypatch.setattr(_loop_answer_evidence, "decide_answer_evidence", decide)


@pytest.mark.asyncio
async def test_an_evidence_refusal_reads_stopped_with_the_native_reason(db, monkeypatch, fake_world):  # noqa: F811
    _sourced_tool(monkeypatch)
    _refusing_decision(monkeypatch)
    monkeypatch.setitem(_SCENARIO_OVERRIDES, "script", [TOOL_RESPONSE, UNCITED, UNCITED])

    session_id, _events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario="evidence")

    final, _records, _reasons = await _outcome(db, session_id)
    assert "withheld" in final, "the delivered refusal is unchanged"
    assert await _final_outcome(db, session_id) == ("stopped", "answer_evidence_uncited")


@pytest.mark.asyncio
async def test_a_marked_answer_still_finishes(db, monkeypatch, fake_world):  # noqa: F811
    """An answer delivered with its sources note is a normal finish, never a stop."""
    _sourced_tool(monkeypatch)
    monkeypatch.setitem(_SCENARIO_OVERRIDES, "script", [TOOL_RESPONSE, UNCITED, UNCITED])

    session_id, _events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario="evidence")

    final, _records, _reasons = await _outcome(db, session_id)
    assert "No source linked" in final
    assert await _final_outcome(db, session_id) == ("finished", None)


@pytest.mark.asyncio
async def test_a_pseudo_tool_call_refusal_is_never_finished(db, monkeypatch, fake_world):  # noqa: F811
    monkeypatch.setitem(_SCENARIO_OVERRIDES, "script", [PSEUDO, PSEUDO])

    session_id, _events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario="evidence")

    final, _records, _reasons = await _outcome(db, session_id)
    assert "wrote tool calls as text" in final
    assert await _final_outcome(db, session_id) == ("unknown", None)


@pytest.mark.asyncio
async def test_an_accepted_answer_still_finishes(db, monkeypatch, fake_world):  # noqa: F811
    _sourced_tool(monkeypatch)
    monkeypatch.setitem(_SCENARIO_OVERRIDES, "script", [TOOL_RESPONSE, CITED])

    session_id, _events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario="evidence")

    assert await _final_outcome(db, session_id) == ("finished", None)
