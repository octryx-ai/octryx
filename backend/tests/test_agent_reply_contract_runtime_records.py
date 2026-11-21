"""A reply-contract record belongs to its own candidate and trace outcome: an earlier candidate's or a corrupt record reads as no record and never raises."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.loops.response._loop_response_guard_inputs import ResponseGuardInputs
from app.models import Message, TurnTrace
from app.services.session.turn_execution_snapshot import AGENT_REPLY_CONTRACT_KEY, TURN_EXECUTION_SNAPSHOT_KEY
from tests.agent_reply_contract_runtime_support import _summary
from tests.agent_tool_surface_runtime_support import _session

SATISFIED_RECORD = {"kind": "json_object", "status": "satisfied", "reason": None}


@pytest.mark.asyncio
async def test_a_record_left_from_an_earlier_candidate_reads_as_no_record_on_a_stop_trace(db):
    """A stop answer persisted with the turn's shared context (as transition, step-tool, fallback and
    duplicate-recovery stops do) never shows an earlier candidate's ``satisfied`` result."""
    from app.agent.core.assistant_message import persist_traced_assistant_message
    from app.agent.core.runtime.turn_execution_binding import (
        bind_turn_execution_snapshot,
        clear_turn_execution_snapshot,
    )
    from app.services.session.execution_gate import evaluate_execution_gate
    from app.services.session.turn_execution_snapshot import build_turn_execution_snapshot

    admin, session = await _session(db)
    user_message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Explain Owner.")
    db.add(user_message)
    await db.commit()
    profile = {
        "version": "execution_profile.v1", "status": "allowed", "profile_id": "direct_chat_safe",
        "decision_source": "direct_chat_safe", "execution_strategy": "direct",
    }
    bind_turn_execution_snapshot(session.id, build_turn_execution_snapshot(
        execution_profile=profile, gate=evaluate_execution_gate(profile),
        session_metadata={"current_turn_user_message_id": user_message.id}, agent_definition=None,
    ))
    try:
        delivered = await persist_traced_assistant_message(
            db=db, session_id=session.id, content="Agent stopped: the final step kept answering without its tools.",
            provider="bedrock", model="m", input_messages=[{"role": "user", "content": "Explain Owner."}],
            context_snapshot={AGENT_REPLY_CONTRACT_KEY: dict(SATISFIED_RECORD)}, runtime_stop_reason="step_stalled",
        )
    finally:
        clear_turn_execution_snapshot(session.id)
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.message_id == delivered.id))).scalar_one()

    summary = await _summary(db, trace)
    assert summary["state"] == "stopped" and summary["reply_contract"] is None


@pytest.mark.asyncio
async def test_each_candidate_starts_without_an_earlier_candidates_record():
    """``handle_response_guards`` drops the record before any guard can end the candidate."""
    from dataclasses import fields

    from app.agent.loops.response._loop_response_guards import handle_response_guards

    seen: dict = {}

    async def persist(**kwargs):
        seen["context"] = dict(kwargs["context_snapshot"])

    class _DB:
        async def commit(self):
            return None

    context = {AGENT_REPLY_CONTRACT_KEY: dict(SATISFIED_RECORD)}
    kwargs = {field.name: None for field in fields(ResponseGuardInputs)}
    kwargs.update(
        db=_DB(), session_id="s", runtime={"provider_name": "bedrock"}, response={}, request_messages=[],
        messages=[], context_snapshot=context, runtime_attempts=[], runtime_settings={}, usage_model="m",
        content="", tool_calls=[{"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}],
        # The first guard that ends a candidate: a completed workflow contract with a late tool call.
        workflow_contract={"workflow_id": "research_document"}, workflow_artifact_ready_for_final_response=True,
        is_transitional_tool_call_preamble=lambda *_a: False, _looks_like_coding_intent_only_response=lambda *_a: False,
        persist_suppressed_runtime_response=persist, consecutive_non_progress_response_count=0,
        consecutive_coding_no_execution_count=0, consecutive_transitional_response_count=0,
    )

    outcome = await handle_response_guards(ResponseGuardInputs(**kwargs))

    assert outcome["action"] == "continue"
    assert AGENT_REPLY_CONTRACT_KEY not in seen["context"] and AGENT_REPLY_CONTRACT_KEY not in context


@pytest.mark.parametrize("record", [
    {"kind": "json_object", "status": "violated", "reason": ["agent_reply_not_json"]},
    {"kind": ["json_object"], "status": "satisfied", "reason": None},
    {"kind": "json_object", "status": {"satisfied": True}, "reason": None},
    {"kind": {"x": 1}, "status": ["violated"], "reason": {"r": 1}},
    {"kind": "json_object", "status": "satisfied", "reason": None, "extra": 1},
    ["kind", "status", "reason"],
])
def test_a_corrupt_record_reads_as_no_record_and_never_raises(record):
    from app.services.session.turn_execution_snapshot import read_agent_reply_contract

    stopped = {"runtime_outcome": "stopped", "runtime_stop_reason": "agent_reply_not_json"}
    for marker in (stopped, {"runtime_outcome": "finished"}, {}):
        assert read_agent_reply_contract({TURN_EXECUTION_SNAPSHOT_KEY: marker, AGENT_REPLY_CONTRACT_KEY: record}) is None


def test_a_record_reads_only_where_it_agrees_with_its_traces_outcome():
    from app.services.session.turn_execution_snapshot import read_agent_reply_contract

    violated = {"kind": "json_object", "status": "violated", "reason": "agent_reply_not_json"}

    def read(record, **marker):
        return read_agent_reply_contract({TURN_EXECUTION_SNAPSHOT_KEY: marker, AGENT_REPLY_CONTRACT_KEY: record})

    assert read(SATISFIED_RECORD, runtime_outcome="finished") == SATISFIED_RECORD
    assert read(SATISFIED_RECORD) is None
    assert read(SATISFIED_RECORD, runtime_outcome="stopped", runtime_stop_reason="answer_evidence_uncited") is None
    assert read(violated, runtime_outcome="stopped", runtime_stop_reason="agent_reply_not_json") == violated
    assert read(violated, runtime_outcome="stopped", runtime_stop_reason="agent_reply_schema_mismatch") is None
    assert read(violated, runtime_outcome="finished") is None
