"""Actual phase boundaries at iteration exhaustion; no synthesized output or canonical proof."""
from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

import app.agent.engine as agent_engine
from app.agent.engine import run_agent
from app.agent.engine.pre_dispatch._research_evidence_context import ResearchEvidenceContextError
from app.agent.loops.control import _loop_terminal_phase as terminal
from app.models import UsageEvent, WorkflowRunEvent
from app.services.workflow_runs.records import new_chat_session, start_run
from app.tools.registry import TOOL_REGISTRY
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
from tests.test_phase_turn_answer_evidence import SEARCH_CALL, _definition, _evidence_tool, _model
from tests.turn_preparation_support import prepare_chat_turn

pytestmark = pytest.mark.asyncio


async def ceiling_case(db, monkeypatch, *, definition=None, during_search=None, twice=False, context_refusal=False):
    user = await admin_user(db)
    workspace_id = await run_workspace(db, user)
    session = await new_chat_session(db, user, workspace_id)
    run = await start_run(db, user=user, workflow_key=await publish_phased(db, definition or _definition()),
                          project_id=workspace_id, session=session)
    await db.commit()
    prompt = "Collect the evidence for this phase."
    await prepare_chat_turn(db=db, user=user, prompt=prompt, session_id=session.id)
    await db.commit()
    _evidence_tool(monkeypatch)
    if during_search:
        original = TOOL_REGISTRY["knowledge_search"].execute

        async def search(params, context):
            result = await original(params, context)
            await during_search(run)
            await db.commit()
            return result

        monkeypatch.setattr(TOOL_REGISTRY["knowledge_search"], "execute", search)
    if twice:
        original_terminal = terminal.record_iteration_ceiling

        async def duplicate(**kwargs):
            await original_terminal(**kwargs)
            await original_terminal(**kwargs)

        monkeypatch.setattr(terminal, "record_iteration_ceiling", duplicate)
    seen = _model(monkeypatch, [copy.deepcopy(SEARCH_CALL)])
    if context_refusal:
        original_chat = agent_engine._chat_with_runtime_fallback

        async def refuse_second(**kwargs):
            if seen:
                raise ResearchEvidenceContextError("research_evidence_does_not_fit")
            return await original_chat(**kwargs)

        monkeypatch.setattr(agent_engine, "_chat_with_runtime_fallback", refuse_second)
    events = [event async for event in run_agent(
        session_id=session.id, user_message=prompt, user_id=user.id, project_id=None,
        agent_type=session.agent_type, db=db, max_iterations=2 if context_refusal else 1,
    )]
    await db.refresh(run)
    rows = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    usage = (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session.id))).scalars().all()
    assert len(seen) == 1 and events
    assert sum(row.tokens_in + row.tokens_out for row in usage) == 15
    return run, rows


def checks_tool(definition, tool):
    definition["nodes"][1]["config"]["workflow_contract"]["checks"][0]["params"]["tools"] = [tool]
    definition["nodes"][2]["config"]["checks"][0]["params"]["tools"] = [tool]
    return definition


async def test_missing_declared_structured_output_never_passes_or_appears_as_fallback_prose(db, monkeypatch):
    definition = checks_tool(_definition(), "submit_test_contract")
    phase = definition["nodes"][1]["config"]
    phase["output"] = "test_contract"
    phase["tool_policy"]["allowlist"].append("submit_test_contract")
    run, rows = await ceiling_case(db, monkeypatch, definition=definition)
    assert run.current_node_id == "work" and run.status == "running"
    assert run.gate_results["work"]["state"] == "not_verified"
    assert "test_contract" not in run.context.get("outputs", {})
    assert not run.context.get("answers", {}).get("work")
    assert sum(row.kind == "phase_turn" for row in rows) == 1
    assert not any(row.kind == "gate_evaluated" for row in rows)
    assert run.budget_usage["tokens"] == 15 and run.budget_usage["tool_calls"] == 1


@pytest.mark.parametrize("drift", ["entry", "node", "status"])
async def test_ceiling_does_not_apply_a_stale_phase_report_to_current_run(db, monkeypatch, drift):
    before = {}

    async def moved(run):
        before.update(copy.deepcopy(run.context))
        if drift == "entry":
            run.node_state = {**run.node_state, "entry": "a-different-current-entry"}
        elif drift == "node":
            run.current_node_id = "verify"
        else:
            run.status = "stopped"

    run, rows = await ceiling_case(db, monkeypatch, during_search=moved)
    assert not any(row.kind in {"phase_turn", "gate_evaluated", "completed"} for row in rows)
    assert not run.gate_results and not run.budget_usage
    assert run.context == before
    if drift == "entry":
        assert run.node_state["entry"] == "a-different-current-entry"
    elif drift == "node":
        assert run.current_node_id == "verify"
    else:
        assert run.status == "stopped"


async def test_two_ceiling_paths_share_one_bound_claim_and_never_double_count_tools(db, monkeypatch):
    definition = checks_tool(_definition(), "knowledge_read")
    run, rows = await ceiling_case(db, monkeypatch, definition=definition, twice=True)
    assert run.status == "running" and run.current_node_id == "work"
    assert run.gate_results["work"]["state"] == "not_verified"
    assert sum(row.kind == "phase_turn" for row in rows) == 1
    assert run.context["evidence"]["work"]["turns"] == 1
    assert run.budget_usage["tool_calls"] == 1 and run.budget_usage["tokens"] == 15


@pytest.mark.parametrize("required,resume", [("knowledge_search", "phase_passed"), ("knowledge_read", "stay")])
async def test_real_ceiling_usage_pauses_at_budget_before_any_phase_advancement(db, monkeypatch, required, resume):
    definition = checks_tool(_definition(), required)
    definition["budget"] = {"tokens": 15, "tool_calls": 1}
    run, rows = await ceiling_case(db, monkeypatch, definition=definition)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "budget_limit", "work")
    assert run.budget_usage["tokens"] == 15 and run.budget_usage["tool_calls"] == 1
    paused = [row for row in rows if row.kind == "paused"]
    assert len(paused) == 1
    assert set(paused[0].detail["keys"]) == {"tokens", "tool_calls"}
    assert paused[0].detail["resume"]["kind"] == resume
    assert sum(row.kind == "phase_turn" for row in rows) == 1
    assert not any(row.kind in {"gate_evaluated", "completed"} for row in rows)


@pytest.mark.parametrize("budget", [False, True])
async def test_context_refusal_keeps_real_prior_usage_without_inventing_a_phase_result(db, monkeypatch, budget):
    definition = checks_tool(_definition(), "knowledge_read")
    if budget:
        definition["budget"] = {"tokens": 15, "tool_calls": 1}
    run, rows = await ceiling_case(db, monkeypatch, definition=definition, context_refusal=True)
    assert run.status == "paused"
    assert run.pause_reason == ("budget_limit" if budget else "needs_configuration")
    assert run.current_node_id == "work" and not run.gate_results
    assert not any(row.kind in {"phase_turn", "gate_evaluated", "completed"} for row in rows)
    assert sum(row.kind == "paused" for row in rows) == 1
    assert run.budget_usage["tokens"] == 15 and run.budget_usage["tool_calls"] == 1
    assert run.node_state["pause"]["resume"]["kind"] == ("stay" if budget else "restart")
