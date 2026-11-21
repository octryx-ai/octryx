"""Workflow agent steps run the selected agent or fail explicitly.

Runtime tests run the real ``agent.engine.run_agent`` end to end; only the provider boundary
(``resolve_control_plane_runtimes`` and ``_chat_with_runtime_fallback``) is a test double, so they
prove the flow wiring, governance and outcome mapping — not a real provider (Codex validates that live).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import FlowNodeRun, Session, User
from app.services.flow_definitions import create_flow_definition
from app.services.flow_orchestration.flow_agent_reference import (
    AGENT_INACTIVE,
    AGENT_NOT_ACCESSIBLE,
    AGENT_OUT_OF_SCOPE,
    FlowAgentReferenceError,
    check_flow_agent_reference,
)
from app.services.flow_orchestration.runner import execute_flow_version
from tests.flow_agent_step_support import ANSWER, _admin_and_project, _agent, _flow, _node_run, _provider_double, uid


@pytest.mark.asyncio
async def test_reference_guard_hides_existence_and_enforces_active_and_scope(db):
    admin, project = await _admin_and_project(db)
    other = User(id=uid(), username=f"other-{uid()}", email=f"{uid()}@example.test", password_hash="!")
    outsider = User(id=uid(), username=f"outsider-{uid()}", email=f"{uid()}@example.test", password_hash="!")
    db.add_all([other, outsider])
    await db.flush()
    foreign = await _agent(db, other.id)
    inactive = await _agent(db, admin.id, active=False)
    scoped = await _agent(db, admin.id, project_id=project.id)
    global_agent = await _agent(db, admin.id)

    async def code(agent_id: str, flow_project: str | None) -> str:
        with pytest.raises(FlowAgentReferenceError) as refusal:
            await check_flow_agent_reference(db, definition_id=agent_id, user_id=admin.id, flow_project_id=flow_project)
        return refusal.value.code

    assert await code(uid(), project.id) == AGENT_NOT_ACCESSIBLE
    # A3: agents are shared; a global admin sees another owner's agent, a Workspace outsider does not.
    assert (await check_flow_agent_reference(db, definition_id=foreign.id, user_id=admin.id, flow_project_id=None)).id
    hidden = await _agent(db, other.id, project_id=project.id)
    with pytest.raises(FlowAgentReferenceError) as refusal:
        await check_flow_agent_reference(db, definition_id=hidden.id, user_id=outsider.id, flow_project_id=project.id)
    assert refusal.value.code == AGENT_NOT_ACCESSIBLE  # identical to "does not exist"
    assert await code(inactive.id, project.id) == AGENT_INACTIVE
    assert await code(scoped.id, None) == AGENT_OUT_OF_SCOPE  # workspace agent in a Global workflow
    assert await code(scoped.id, uid()) == AGENT_OUT_OF_SCOPE
    assert (
        await check_flow_agent_reference(db, definition_id=scoped.id, user_id=admin.id, flow_project_id=project.id)
    ).id == scoped.id
    assert (
        await check_flow_agent_reference(db, definition_id=global_agent.id, user_id=admin.id, flow_project_id=None)
    ).id == global_agent.id


@pytest.mark.asyncio
async def test_creating_a_workflow_with_an_unavailable_agent_is_refused_without_naming_it(db):
    admin, project = await _admin_and_project(db)
    inactive = await _agent(db, admin.id, active=False)
    definition = {
        "schema_version": "2.0",
        "nodes": [
            {"id": "start", "type": "trigger", "config": {"trigger_type": "manual"}},
            {"id": "a", "type": "agent_step", "config": {"agent_definition_id": inactive.id}},
            {"id": "end", "type": "output"},
        ],
        "edges": [{"source_node_id": "start", "target_node_id": "a"}, {"source_node_id": "a", "target_node_id": "end"}],
    }
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refusal:
        await create_flow_definition(
            db,
            current_user=admin,
            payload={"key": f"k-{uid()}", "name": "n", "project_id": project.id, "definition": definition},
        )
    detail = refusal.value.detail
    assert refusal.value.status_code == 422 and detail["valid"] is False
    assert AGENT_INACTIVE in [error["code"] for error in detail["errors"]]
    assert inactive.name not in str(detail)


@pytest.mark.asyncio
async def test_a_selected_agent_really_runs_and_its_answer_reaches_the_output(db, monkeypatch):
    admin, project = await _admin_and_project(db)
    agent = await _agent(db, admin.id, project_id=project.id)
    calls = _provider_double(monkeypatch)
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Summarise the request."})

    run = await execute_flow_version(
        db,
        flow_version_id=version.id,
        project_id=project.id,
        user_id=admin.id,
        initial_input={"request": "demo service down 2 min, auto-recovered"},
    )

    assert run.status == "completed", run.last_error
    node = await _node_run(db, run, "summarise")
    assert node.status == "completed"
    output = node.output_json
    assert output["result"] == ANSWER and output["result"] != "demo service down 2 min, auto-recovered"
    assert output["agent"]["definition_id"] == agent.id and output["agent"]["source"] == "live_draft_row"
    assert output["turn"]["state"] == "finished_unverified" and "verification" not in output["turn"]
    assert output["turn"]["provider"] and output["turn"]["model"] and output["turn"]["trace_id"]
    child = await db.get(Session, output["session_id"])
    assert child.parent_session_id == run.session_id and child.project_id == project.id
    assert child.metadata_["flow_agent_definition_id"] == agent.id
    # One-turn child sessions end terminal, never left "active" after the flow completed.
    assert child.status == "completed" and child.ended_at is not None
    # The real runtime built the turn: the agent's system prompt and the step task reached the model.
    sent = " ".join(str(message.get("content")) for message in calls[-1])
    assert "Summarise the incident in one sentence." in sent and "Workflow step input (JSON)" in sent
    final = (await _node_run(db, run, "end")).output_json
    assert ANSWER in str(final)


@pytest.mark.asyncio
async def test_a_provider_failure_fails_the_node_and_nothing_downstream_completes(db, monkeypatch):
    admin, project = await _admin_and_project(db)
    agent = await _agent(db, admin.id, project_id=project.id)
    _provider_double(monkeypatch, raise_error=RuntimeError("provider unavailable"))
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Summarise."})

    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "x"}
    )

    assert run.status == "failed"
    node = await _node_run(db, run, "summarise")
    assert node.status == "failed" and node.error.startswith("agent_turn_")
    assert (
        await db.execute(
            select(FlowNodeRun).where(FlowNodeRun.orchestrator_run_id == run.id, FlowNodeRun.node_id == "end")
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_an_agent_deactivated_after_authoring_fails_at_run_time_without_running(db, monkeypatch):
    admin, project = await _admin_and_project(db)
    agent = await _agent(db, admin.id, project_id=project.id)
    calls = _provider_double(monkeypatch)
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Summarise."})
    agent.is_active = False
    await db.flush()

    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "x"}
    )

    assert run.status == "failed" and calls == []
    assert (await _node_run(db, run, "summarise")).error.startswith(AGENT_INACTIVE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_type", "config", "code"),
    [
        ("agent_step", {"mock_output": {"ok": True}}, "agent_step_needs_agent"),
        ("supervisor", {"prompt": "Coordinate."}, "supervisor_execution_unsupported"),
    ],
)
async def test_steps_without_an_executable_agent_fail_explicitly_instead_of_passing_input_on(
    db, monkeypatch, node_type, config, code
):
    admin, project = await _admin_and_project(db)
    calls = _provider_double(monkeypatch)
    version = await _flow(db, admin, project.id, config, node_type=node_type)

    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "x"}
    )

    assert run.status == "failed" and calls == []
    assert (await _node_run(db, run, "summarise")).error.startswith(code)
