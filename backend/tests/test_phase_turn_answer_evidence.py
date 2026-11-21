"""A phase turn's result reaches its run even when a guard ends or marks its prose.

When an Engineer submits test contract v1 and its prose summary has no source links, the answer evidence guard
reminds and may end the turn before the workflow checks guard runs, so ``record_phase_turn`` would never report the
phase. Exempting run turns from the guard is no answer: uncited prose must not pass unmarked. The guard applies to
run turns as to chat, and a turn a guard ends (citation refusal, reply-contract stop) still evaluates and records its
checks once; failed checks stay ``not_verified``.

The citation guard never withholds: after its one reminder, uncited prose is delivered with a sources note
(``marked``). There is no run-turn exemption: a phase turn's prose is marked like a chat's.

Real path: turn preparation on a session bound to a running phased run, then ``run_agent`` with a scripted model.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.loops.response._loop_response_guards as response_guards
from app.agent.engine import run_agent
from app.models import Message, TurnTrace, WorkflowRunEvent
from app.services.answer_evidence.decision import ACTION_MARK, decide_answer_evidence
from app.services.answer_evidence.record import read_answer_evidence
from app.services.answer_evidence.texts import REMINDER_MARKER
from app.services.workflow_runs.records import new_chat_session, start_run
from app.tools.registry import TOOL_REGISTRY
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.turn_preparation_support import prepare_chat_turn

SOURCE = "https://wiki.example.test/textkit/truncate-words"
UNCITED = (
    "The function truncate_words keeps the first n words and joins them with single spaces.\n\n"
    "- A negative count raises ValueError.\n- Zero words returns an empty string.\n"
)
CITED = f"The function truncate_words keeps the first n words ([truncate_words]({SOURCE})).\n"
SEARCH_CALL = {"content": "", "tool_calls": [
    {"id": "call-search", "function": {"name": "knowledge_search", "arguments": '{"query": "truncate_words"}'}}]}


def _evidence_tool(monkeypatch) -> None:
    async def search(params, context):
        return {"state": "ok", "result_count": 1, "evidence": [{
            "title": "truncate_words", "content": "truncate_words keeps the first n words.",
            "source_url": SOURCE, "cite_as": f"[truncate_words]({SOURCE})"}]}

    monkeypatch.setattr(TOOL_REGISTRY["knowledge_search"], "execute", search)


def _model(monkeypatch, replies: list[dict]) -> list[list[dict]]:
    seen: list[list[dict]] = []

    async def fake_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5"}]

    async def fake_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None, **_kwargs):
        seen.append(list(messages))
        reply = replies.pop(0)
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return {"tool_calls": None, "model": "anthropic.claude-sonnet-4-5", **reply, "usage": usage}, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat)
    return seen


def _definition(*, phase_check_tool: str = "knowledge_search") -> dict:
    definition = phased_definition()
    definition["nodes"][1]["config"]["workflow_contract"]["checks"][0]["params"]["tools"] = [phase_check_tool]
    return definition


async def _phase_turn(db, monkeypatch, replies: list[dict], *, definition: dict | None = None):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition or _definition()),
                          project_id=workspace_id,
                          session=session)
    await db.commit()
    prompt = "Collect the evidence for the item."
    session, _runtime, _thinking, _agent = await prepare_chat_turn(db=db, user=admin, prompt=prompt,
                                                                   session_id=session.id)
    await db.commit()
    _evidence_tool(monkeypatch)
    seen = _model(monkeypatch, replies)
    contents: list[str] = []
    async for event in run_agent(session_id=session.id, user_message=prompt, user_id=admin.id, project_id=None,
                                 agent_type=session.agent_type, db=db):
        if getattr(event, "role", "") == "assistant" and getattr(event, "content", ""):
            contents.append(str(event.content))
    await db.refresh(run)
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id)
                               .order_by(TurnTrace.created_at))).scalars().all()
    records = [record for trace in traces if (record := read_answer_evidence(trace.context_snapshot_json))]
    stored = [str(row.content) for row in (await db.execute(select(Message).where(
        Message.session_id == session.id, Message.role == "assistant"))).scalars()]
    kinds = [(event.kind, event.node_id) for event in (await db.execute(
        select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars()]
    return run, seen, contents, records, stored, kinds


def _gate(run) -> str:
    return str((dict(run.gate_results or {}).get("work") or {}).get("state") or "")


@pytest.mark.asyncio
async def test_uncited_phase_prose_is_delivered_marked_and_the_phase_result_still_reaches_the_run(db, monkeypatch):
    run, seen, contents, records, stored, kinds = await _phase_turn(
        db, monkeypatch, [SEARCH_CALL, {"content": UNCITED}, {"content": UNCITED}])

    assert len(seen) == 3, "evidence call, uncited reply, the citation reminder, uncited again"
    assert any(str(m.get("content") or "").startswith(REMINDER_MARKER) for m in seen[-1])
    assert "withheld" not in contents[-1] and "keeps the first n words" in contents[-1]
    assert "No source linked" in contents[-1] and SOURCE in contents[-1]
    assert any("No source linked" in text for text in stored), "the stored answer is the marked one"
    assert [record["evidence_guard"] for record in records][-2:] == ["reminded", "marked"]
    # The phase result the turn earned is recorded exactly once and the run evaluated its gate on it.
    assert _gate(run) == "passed", run.gate_results
    assert kinds.count(("phase_turn", "work")) == 1
    assert ("gate_evaluated", "verify") in kinds


@pytest.mark.asyncio
async def test_a_marked_reply_never_turns_failed_checks_into_a_pass(db, monkeypatch):
    # The phase check needs knowledge_read, never called: after the marked reply the checks guard reminds once, then
    # records not_verified once, no gate pass.
    run, _seen, contents, _records, _stored, kinds = await _phase_turn(
        db, monkeypatch, [SEARCH_CALL, {"content": UNCITED}, {"content": UNCITED}, {"content": UNCITED}],
        definition=_definition(phase_check_tool="knowledge_read"))

    assert "withheld" not in contents[-1]
    assert _gate(run) == "not_verified", run.gate_results
    assert kinds.count(("phase_turn", "work")) == 1
    assert ("gate_evaluated", "verify") not in kinds


@pytest.mark.asyncio
async def test_a_reply_contract_stop_also_records_the_phase_result(db, monkeypatch):
    async def stop(**kwargs):  # the reply-contract check stops a cited candidate (its own contract tests: elsewhere)
        if kwargs["tool_calls"]:
            return None  # like the real check: only a final candidate is checked
        return {"action": "return", "yield_content": kwargs["content"], "yield_model": kwargs["usage_model"]}

    monkeypatch.setattr(response_guards, "handle_reply_contract_check", stop)
    run, seen, _contents, _records, _stored, kinds = await _phase_turn(
        db, monkeypatch, [SEARCH_CALL, {"content": CITED}])

    assert len(seen) == 2  # the stop ended the turn at the cited candidate
    assert _gate(run) == "passed", run.gate_results
    assert kinds.count(("phase_turn", "work")) == 1


@pytest.mark.asyncio
async def test_a_checks_reminder_then_acceptance_records_once(db, monkeypatch):
    # No source in the turn: the citation guard has nothing to withhold; the checks guard reminds once, then the run
    # gets exactly one not_verified result.
    run, seen, contents, _records, _stored, kinds = await _phase_turn(
        db, monkeypatch, [{"content": UNCITED}, {"content": UNCITED}])

    assert len(seen) == 2 and contents[-1] == UNCITED
    assert _gate(run) == "not_verified", run.gate_results
    assert kinds.count(("phase_turn", "work")) == 1


def test_phase_result_reporting_does_not_exempt_an_uncited_visible_answer_from_marking():
    # Regression: there is no run-turn exemption in the shared answer-evidence decision.
    history = [{"tool_name": "knowledge_search", "status": "success",
                "result": {"results": [{"source_url": SOURCE, "cite_as": f"[t]({SOURCE})", "content": "x"}]}}]
    assert "phase_turn" not in inspect.signature(decide_answer_evidence).parameters
    decision = decide_answer_evidence(content=UNCITED, turn_tool_history=history, user_message="q", reminders=1,
                                      capability_type="diagnosis", sub_agent_depth=0)
    assert decision.action == ACTION_MARK, decision
    assert decision.content.startswith(UNCITED.rstrip()) and "No source linked" in decision.content
