"""Independent acceptance: a withheld final answer has a recorded stop."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.loops.response._loop_answer_evidence import handle_answer_evidence_guard
from app.services.answer_evidence.record import ANSWER_EVIDENCE_KEY
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
)
from app.services.session.turn_execution_summary import (
    TurnExecutionEvidence,
    build_turn_execution_summary,
    runtime_outcome_from_trace,
)
from tests.test_harness_refusal_outcome import _refusing_decision

_URL = "https://example.org/owner.java"
_HISTORY = [{"tool_name": "web_fetch", "result": {
    "source_url": _URL, "content": "Owner holds a list of pets.",
}}]


def _context():
    profile = {
        "version": "execution_profile.v1", "status": "allowed",
        "profile_id": "explicit-repository", "decision_source": "explicit_workflow_key",
        "execution_strategy": "workflow", "effective_agent_type": "diagnosis",
        "workflow_id": "repository-questions",
    }
    return {TURN_EXECUTION_SNAPSHOT_KEY: build_turn_execution_snapshot(
        execution_profile=profile, gate=evaluate_execution_gate(profile),
        session_metadata={}, agent_definition=None,
    )}


async def _call_guard(content, messages, context):
    persisted = []

    async def persist(**kwargs):
        persisted.append(deepcopy(kwargs))

    outcome = await handle_answer_evidence_guard(
        db=SimpleNamespace(commit=AsyncMock()), session_id="judge-session",
        runtime={"provider_name": "bedrock"}, usage_model="test-model",
        response={"usage": {"prompt_tokens": 12, "completion_tokens": 4}},
        request_messages=[{"role": "user", "content": "Explain the Owner class."}],
        messages=messages, context_snapshot=context, runtime_attempts=[], runtime_settings={},
        content=content, tool_calls=[], capability_type="diagnosis", has_followup_steps=False,
        sub_agent_depth=0, turn_tool_history=_HISTORY,
        persist_turn_trace=persist, persist_traced_assistant_message=persist,
    )
    return outcome, persisted


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,reason", [
    ("Owner holds a list of pets.", "answer_evidence_uncited"),
    ("Owner holds a list of pets ([Owner](https://example.org/invented.java)).", "answer_evidence_invented_url"),
])
async def test_final_evidence_refusal_persists_a_non_success_terminal_status(answer, reason, monkeypatch):
    # The guard no longer refuses: the refusal is forced to keep its stop contract.
    _refusing_decision(monkeypatch)
    context, messages = _context(), []
    first, _ = await _call_guard(answer, messages, context)
    assert first["action"] == "continue"
    final, persisted = await _call_guard(answer, messages, context)
    assert final["action"] == "return"
    payload = persisted[0]
    assert payload["raw_output"]["refusal_reason"] == reason
    assert payload["context_snapshot"][ANSWER_EVIDENCE_KEY]["evidence_guard"] == "refused"
    assert answer not in final["yield_content"]
    outcome = runtime_outcome_from_trace(payload["context_snapshot"], payload["raw_output"])
    assert outcome == "stopped", "A terminal refusal must not leave runtime status unknown"
    summary = build_turn_execution_summary(TurnExecutionEvidence(
        trace_id="trace-1", session_id="judge-session", message_id="message-1",
        provider="bedrock", model="test-model", context_snapshot=payload["context_snapshot"],
        runtime_outcome=outcome,
    ))
    assert summary["state"] == "stopped"
    assert summary["answer_evidence"]["evidence_guard"] == "refused"


@pytest.mark.asyncio
async def test_first_evidence_reminder_is_not_a_terminal_stop():
    first, persisted = await _call_guard("Owner holds a list of pets.", [], _context())
    assert first["action"] == "continue"
    assert persisted[0]["raw_output"]["suppressed_for_answer_evidence"] is True
    assert runtime_outcome_from_trace(persisted[0]["context_snapshot"], persisted[0]["raw_output"]) == "unknown"


@pytest.mark.asyncio
async def test_correctly_cited_answer_keeps_the_normal_completion_path():
    context = _context()
    outcome, persisted = await _call_guard(f"Owner holds a list of pets ([Owner]({_URL})).", [], context)
    assert outcome is None
    assert persisted == []
    assert context[ANSWER_EVIDENCE_KEY]["evidence_guard"] == "passed"
