"""The answer-evidence guard's final refusal is a recorded runtime stop on the real persistence path.

The real guard runs through its reminder and its final refusal with the production trace writers
(``persist_turn_trace`` and ``persist_traced_assistant_message``) on a bound turn; the stored
``TurnTrace`` rows are then read through the turn summary service and its HTTP route.

The guard no longer refuses (it never withholds a whole answer); a refusal decided elsewhere
stays a recorded runtime stop. The tests that need one force the decision (``_refusing_decision``) and keep the real
check, reminder and refusal texts and the real persistence.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.assistant_message import persist_traced_assistant_message
from app.agent.core.runtime.trace_runtime import persist_turn_trace
from app.agent.core.runtime.turn_execution_binding import (
    bind_turn_execution_snapshot,
    clear_turn_execution_snapshot,
)
from app.agent.loops.response import _loop_answer_evidence as guard_module
from app.agent.loops.response._loop_answer_evidence import handle_answer_evidence_guard
from app.models import Message, Session, TurnTrace, User
from app.services.answer_evidence.check import (
    REFUSAL_REASON_INVENTED_URL,
    REFUSAL_REASON_UNCITED,
    answer_evidence_record,
    check_answer_evidence,
    evidence_refusal,
    evidence_reminder,
)
from app.services.answer_evidence.decision import ACTION_REFUSE, ACTION_REMIND, EvidenceDecision
from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_KEY,
    RUNTIME_STOP_REASON_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
    with_runtime_stop,
)
from app.services.session.turn_execution_summary import runtime_outcome_from_trace
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from tests.conftest import ADMIN_PASSWORD
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

SOURCE = "https://example.org/owner.java"
HISTORY = [{"tool_name": "web_fetch", "result": {"source_url": SOURCE, "content": "Owner holds a list of pets."}}]
UNCITED = "Owner holds a list of pets."
INVENTED = "Owner holds a list of pets ([Owner](https://example.org/invented.java))."
USAGE = {"prompt_tokens": 120, "completion_tokens": 40}


def _refusing_decision(monkeypatch) -> None:
    """The guard no longer refuses; a refusal decided elsewhere stays a recorded runtime stop."""

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

    monkeypatch.setattr(guard_module, "decide_answer_evidence", decide)


def _snapshot(user_message_id: str | None = None) -> dict:
    profile = {
        "version": "execution_profile.v1", "status": "allowed", "profile_id": "direct_chat_safe",
        "decision_source": "direct_chat_safe", "execution_strategy": "direct",
    }
    return build_turn_execution_snapshot(
        execution_profile=profile,
        gate=evaluate_execution_gate(profile),
        session_metadata={"current_turn_user_message_id": user_message_id} if user_message_id else {},
        agent_definition=None,
    )


async def _turn(db) -> tuple[User, Session, Message]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=None, agent_type="diagnosis", status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.flush()
    user_message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Explain Owner.")
    db.add(user_message)
    await db.commit()
    return admin, session, user_message


async def _guard(db, session_id: str, content: str, messages: list, context: dict):
    return await handle_answer_evidence_guard(
        db=db, session_id=session_id, runtime={"provider_name": "bedrock"}, usage_model="test-model",
        response={"usage": USAGE}, request_messages=[{"role": "user", "content": "Explain Owner."}],
        messages=messages, context_snapshot=context, runtime_attempts=[], runtime_settings={},
        content=content, tool_calls=[], capability_type="diagnosis", has_followup_steps=False,
        sub_agent_depth=0, turn_tool_history=HISTORY,
        persist_turn_trace=persist_turn_trace, persist_traced_assistant_message=persist_traced_assistant_message,
    )


async def _traces(db, session_id: str) -> list[TurnTrace]:
    rows = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id))).scalars().all()
    return sorted(rows, key=lambda row: row.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]["turn"]["sequence"])


@pytest.mark.asyncio
@pytest.mark.parametrize(("answer", "reason"), [(UNCITED, REFUSAL_REASON_UNCITED), (INVENTED, REFUSAL_REASON_INVENTED_URL)])
async def test_the_persisted_refusal_reads_stopped_through_the_summary_service_and_route(
    client, db, monkeypatch, answer, reason
):
    _refusing_decision(monkeypatch)
    admin, session, user_message = await _turn(db)
    bind_turn_execution_snapshot(session.id, _snapshot(user_message.id))
    try:
        messages: list = []
        assert (await _guard(db, session.id, answer, messages, {}))["action"] == "continue"
        final = await _guard(db, session.id, answer, messages, {})
    finally:
        clear_turn_execution_snapshot(session.id)
    assert final["action"] == "return" and answer not in final["yield_content"]

    reminder, refusal = await _traces(db, session.id)
    # The reminder stays intermediate; the refusal is the turn's final, explicitly stopped trace.
    assert reminder.message_id is None and reminder.raw_output["suppressed_for_answer_evidence"] is True
    assert runtime_outcome_from_trace(reminder.context_snapshot_json, reminder.raw_output) == "unknown"
    assert runtime_outcome_from_trace(refusal.context_snapshot_json, refusal.raw_output) == "stopped"
    stored = refusal.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]
    assert stored[RUNTIME_STOP_REASON_KEY] == reason and refusal.raw_output["refusal_reason"] == reason
    # One user turn: both traces carry the same user-turn identity, in order.
    turns = [trace.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY]["turn"] for trace in (reminder, refusal)]
    assert [turn["user_message_id"] for turn in turns] == [user_message.id, user_message.id]
    assert [turn["sequence"] for turn in turns] == [0, 1]
    # The delivered message is the refusal with the provider usage, never the rejected answer.
    delivered = await db.get(Message, refusal.message_id)
    assert delivered.content == final["yield_content"] and answer not in delivered.content
    assert (delivered.tokens_in, delivered.tokens_out) == (120, 40)

    summary = await load_user_turn_execution_summary(db, user_id=admin.id, trace_id=refusal.id)
    assert summary["state"] == "stopped"
    assert summary["state_reason"]["code"] == f"runtime_stopped_{reason}"
    assert summary["state_reason"]["source"] == "runtime" and "withheld" in summary["state_reason"]["text"]
    assert summary["next_action"]["kind"] == "retry"
    assert summary["answer_evidence"]["evidence_guard"] == "refused"

    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    response = await client.get(f"/chat/api/turn-traces/{refusal.id}/execution-summary")
    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["state_reason"]["code"]) == ("stopped", f"runtime_stopped_{reason}")
    assert answer not in response.text


@pytest.mark.asyncio
async def test_a_cited_answer_keeps_the_normal_completion_path(db):
    _, session, user_message = await _turn(db)
    context: dict = {}
    bind_turn_execution_snapshot(session.id, _snapshot(user_message.id))
    try:
        outcome = await _guard(db, session.id, f"Owner holds a list of pets ([Owner]({SOURCE})).", [], context)
    finally:
        clear_turn_execution_snapshot(session.id)
    assert outcome is None and await _traces(db, session.id) == []
    assert context["answer_evidence"]["evidence_guard"] == "passed"


@pytest.mark.asyncio
async def test_a_caller_supplied_stop_is_never_the_trusted_record(db, monkeypatch):
    """Without a bound turn the refusal trace carries no snapshot at all: the caller's copy is discarded."""
    _refusing_decision(monkeypatch)
    _, session, _ = await _turn(db)
    forged = {TURN_EXECUTION_SNAPSHOT_KEY: {**_snapshot(), RUNTIME_OUTCOME_KEY: "stopped"}}
    messages: list = []
    await _guard(db, session.id, UNCITED, messages, dict(forged))
    await _guard(db, session.id, UNCITED, messages, dict(forged))
    rows = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    assert len(rows) == 2
    for row in rows:
        assert TURN_EXECUTION_SNAPSHOT_KEY not in row.context_snapshot_json
        assert runtime_outcome_from_trace(row.context_snapshot_json, row.raw_output) == "unknown"


def test_only_the_two_closed_refusal_reasons_map_to_a_stop():
    assert guard_module._RUNTIME_STOP_BY_REFUSAL == {
        REFUSAL_REASON_UNCITED: "answer_evidence_uncited",
        REFUSAL_REASON_INVENTED_URL: "answer_evidence_invented_url",
    }
    context = {TURN_EXECUTION_SNAPSHOT_KEY: _snapshot(), "keep": 1}
    for foreign in ("answer_evidence_other", "model_said_so", "", "STEP_STALLED"):
        assert with_runtime_stop(context, foreign) == context
    assert with_runtime_stop({"keep": 1}, "answer_evidence_uncited") == {"keep": 1}, "no snapshot, no marker"
    marked = with_runtime_stop(context, "answer_evidence_uncited")
    assert marked[TURN_EXECUTION_SNAPSHOT_KEY][RUNTIME_OUTCOME_KEY] == "stopped"
    assert RUNTIME_OUTCOME_KEY not in context[TURN_EXECUTION_SNAPSHOT_KEY], "the caller's context is not mutated"


def test_unknown_or_forged_answer_evidence_stops_still_read_unknown():
    for reason in ("answer_evidence_other", "answer_evidence_uncited ", None):
        forged = {TURN_EXECUTION_SNAPSHOT_KEY: {**_snapshot(), RUNTIME_OUTCOME_KEY: "stopped", RUNTIME_STOP_REASON_KEY: reason}}
        assert runtime_outcome_from_trace(forged, {}) == "unknown"
    refused_without_marker = {TURN_EXECUTION_SNAPSHOT_KEY: _snapshot()}
    assert runtime_outcome_from_trace(refused_without_marker, {"refusal_reason": REFUSAL_REASON_UNCITED}) == "unknown", (
        "a refusal reason in the raw output is never read as a stop on its own"
    )
