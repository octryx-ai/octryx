"""A workflow run phase's turn: chat reminds once on a failed blocking check and accepts the answer as not_verified,
a strict step reminds twice, and results are stored per turn and listed."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.loops.response._loop_workflow_checks import REMINDER_MARKER, handle_workflow_checks_guard
from app.models import Session, User, WorkflowCheckResult
from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
from app.services.workflow_checks.results import WORKFLOW_CHECKS_KEY, read_workflow_checks
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.workflow_checks_support import KNOWLEDGE_CHECKS


def _phase_analysis(contract: dict) -> dict:
    """A workflow run phase's turn: the phase's inline contract governs it."""
    return {ROUTING_RESOLUTION_KEY: {
        "source": "db", "status": "matched", "selection_source": "workflow_run",
        "workflow_key": "answer-docs", "workflow_id": "knowledge_request", "workflow_contract": contract,
    }}


def _resolution(checks):
    return _phase_analysis({"checks": checks})


async def _chat_session(db) -> str:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, status="active", metadata_={})
    db.add(session)
    await db.flush()
    return session.id


async def _guard(db, session_id, *, messages, history, analysis, snapshot, traces):
    async def persist_turn_trace(**kwargs):
        traces.append(kwargs)

    return await handle_workflow_checks_guard(
        db=db, session_id=session_id, runtime={"provider_name": "test"}, response={"usage": {}},
        request_messages=[], messages=messages, context_snapshot=snapshot, runtime_attempts=[],
        runtime_settings={}, usage_model="m", content="The answer.", tool_calls=None, has_followup_steps=False,
        sub_agent_depth=0, request_analysis=analysis, turn_tool_history=history, persist_turn_trace=persist_turn_trace,
    )


@pytest.mark.asyncio
async def test_chat_reminds_once_then_accepts_the_answer_as_not_verified(db):
    session_id = await _chat_session(db)
    messages, snapshot, traces = [], {}, []
    with prompt_set_scope(seed_prompt_set()):
        first = await _guard(db, session_id, messages=messages, history=[], analysis=_resolution(KNOWLEDGE_CHECKS),
                             snapshot=snapshot, traces=traces)
        assert first == {"action": "continue"}
        assert messages[-1]["role"] == "system" and messages[-1]["content"].startswith(REMINDER_MARKER)
        assert "answer-docs" in messages[-1]["content"] and "Evidence retrieved" in messages[-1]["content"]
        assert traces[0]["raw_output"]["suppressed_for_workflow_checks"] is True
        second = await _guard(db, session_id, messages=messages, history=[], analysis=_resolution(KNOWLEDGE_CHECKS),
                              snapshot=snapshot, traces=traces)
    assert second is None
    record = read_workflow_checks(snapshot)
    assert (record["state"], record["reminded"]) == ("not_verified", True)
    rows = (await db.execute(select(WorkflowCheckResult).where(WorkflowCheckResult.session_id == session_id))).scalars()
    assert [(row.runtime, row.state) for row in rows] == [("chat", "not_verified")]


@pytest.mark.asyncio
async def test_chat_passes_without_reminder_and_skips_turns_without_checks(db):
    session_id = await _chat_session(db)
    messages, snapshot, traces = [], {}, []
    history = [{"tool_name": "knowledge_read", "status": "success", "result": {}}]
    with prompt_set_scope(seed_prompt_set()):
        accepted = await _guard(db, session_id, messages=messages, history=history,
                                analysis=_resolution(KNOWLEDGE_CHECKS), snapshot=snapshot, traces=traces)
        assert accepted is None and messages == [] and traces == []
        assert snapshot[WORKFLOW_CHECKS_KEY]["state"] == "passed"
        unselected = {}
        assert await _guard(db, session_id, messages=[], history=[], analysis={}, snapshot=unselected,
                            traces=traces) is None
    assert WORKFLOW_CHECKS_KEY not in unselected


@pytest.mark.asyncio
async def test_the_stored_results_are_listed_per_workflow(client, auth_headers, db):
    session_id = await _chat_session(db)
    passed = [{"tool_name": "knowledge_read", "status": "success", "result": {}}]
    with prompt_set_scope(seed_prompt_set()):
        await _guard(db, session_id, messages=[], history=passed, analysis=_resolution(KNOWLEDGE_CHECKS),
                     snapshot={}, traces=[])
    await db.commit()

    listed = await client.get("/api/v1/workflow-checks/results?workflow_key=answer-docs", headers=auth_headers)
    assert listed.status_code == 200
    assert [(row["runtime"], row["state"]) for row in listed.json()["results"]] == [("chat", "passed")]
    assert "tool_called" in listed.json()["check_types"]


@pytest.mark.asyncio
async def test_a_guided_step_reminds_once_and_a_strict_step_twice(db):
    contract = {"capability_class": "read_only", "source_steps": [{"tool": "knowledge_search", "evidence_label": "sources"}]}
    analysis = _phase_analysis(contract)
    session_id = await _chat_session(db)
    messages, traces = [], []
    with prompt_set_scope(seed_prompt_set()):
        first = await _guard(db, session_id, messages=messages, history=[], analysis=analysis, snapshot={}, traces=traces)
        second = await _guard(db, session_id, messages=messages, history=[], analysis=analysis, snapshot={}, traces=traces)
        assert (first, second) == ({"action": "continue"}, None)
        contract["source_steps"][0]["mode"] = "strict"
        strict_messages = []
        outcomes = [
            await _guard(db, session_id, messages=strict_messages, history=[], analysis=analysis, snapshot={},
                         traces=traces)
            for _ in range(3)
        ]
    assert outcomes == [{"action": "continue"}, {"action": "continue"}, None]
