"""A real governed turn at the iteration ceiling records checks and actual usage once."""

import pytest
from sqlalchemy import select

from app.agent.engine import run_agent
from app.models import WorkflowRunEvent
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
from tests.test_phase_turn_answer_evidence import SEARCH_CALL, _definition, _evidence_tool, _model
from tests.turn_preparation_support import prepare_chat_turn


@pytest.mark.asyncio
@pytest.mark.parametrize("required, expected", [("knowledge_search", "passed"), ("knowledge_read", "not_verified")])
async def test_iteration_ceiling_records_the_real_phase_without_inventing_missing_evidence(
    db, monkeypatch, required, expected,
):
    user = await admin_user(db)
    workspace_id = await run_workspace(db, user)
    session = await new_chat_session(db, user, workspace_id)
    definition = _definition(phase_check_tool=required)
    # The turn and gate both require the same evidence; missing evidence never advances.
    definition["nodes"][2]["config"]["checks"][0]["params"]["tools"] = [required]
    run = await start_run(db, user=user, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    await db.commit()
    prompt = "Collect the evidence for this phase."
    await prepare_chat_turn(db=db, user=user, prompt=prompt, session_id=session.id)
    await db.commit()
    _evidence_tool(monkeypatch)
    seen = _model(monkeypatch, [SEARCH_CALL])
    events = [event async for event in run_agent(
        session_id=session.id, user_message=prompt, user_id=user.id, project_id=None,
        agent_type=session.agent_type, db=db, max_iterations=1,
    )]
    await db.refresh(run)
    recorded = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    assert len(seen) == 1 and events
    assert sum(row.kind == "phase_turn" and row.node_id == "work" for row in recorded) == 1
    assert run.gate_results["work"]["state"] == expected
    assert run.budget_usage["tokens"] == 15
    assert run.budget_usage["tool_calls"] == 1
    if expected == "not_verified":
        assert run.current_node_id == "work"
        assert not any(row.kind == "gate_evaluated" for row in recorded)
    else:
        assert run.status == "completed"


@pytest.mark.asyncio
async def test_iteration_ceiling_never_accounts_an_unbound_chat(monkeypatch):
    from app.agent.loops.control import _loop_terminal_phase as terminal

    async def forbidden(**kwargs):
        pytest.fail("ordinary chat must not record phase checks")

    monkeypatch.setattr(terminal, "record_checks_for_ended_turn", forbidden)
    await terminal.record_iteration_ceiling(db=None, session_id="chat", state={}, shared={})


@pytest.mark.asyncio
async def test_an_explicit_research_context_refusal_pauses_before_provider_without_a_phase_pass(db, monkeypatch):
    import app.agent.engine as engine
    from app.agent.engine.pre_dispatch._research_evidence_context import ResearchEvidenceContextError

    user = await admin_user(db)
    workspace_id = await run_workspace(db, user)
    session = await new_chat_session(db, user, workspace_id)
    run = await start_run(db, user=user, workflow_key=await publish_phased(db, _definition()),
                          project_id=workspace_id, session=session)
    await db.commit()
    prompt = "Collect current evidence."
    await prepare_chat_turn(db=db, user=user, prompt=prompt, session_id=session.id)
    await db.commit()
    _evidence_tool(monkeypatch)
    _model(monkeypatch, [])  # Only select a runtime; the dispatch below refuses before any model response.

    async def refuse(**kwargs):
        raise ResearchEvidenceContextError("research_evidence_does_not_fit")

    monkeypatch.setattr(engine, "_chat_with_runtime_fallback", refuse)
    events = [event async for event in run_agent(
        session_id=session.id, user_message=prompt, user_id=user.id, project_id=None,
        agent_type=session.agent_type, db=db, max_iterations=1,
    )]
    await db.refresh(run)
    recorded = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    assert run.status == "paused" and run.pause_reason == "needs_configuration"
    assert run.node_state["pause"]["reason"] == "research_evidence_does_not_fit"
    assert run.budget_usage["tokens"] == 0 and run.budget_usage["tool_calls"] == 0
    assert not any(row.kind in {"phase_turn", "gate_evaluated"} for row in recorded)
    assert sum(row.kind == "paused" for row in recorded) == 1
    assert any("could not" in str(getattr(event, "content", "")) or "unavailable" in str(getattr(event, "content", ""))
               for event in events)
