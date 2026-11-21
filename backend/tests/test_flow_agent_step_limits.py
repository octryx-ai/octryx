"""Agent references validate only against an explicit context, an unpublished execution mode is an explicit configuration state, and time limits, oversized input and failed turns fail the step cleanly."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.models import FlowDefinitionVersion, FlowNodeRun, Session
from app.services.flow_orchestration.flow_agent_reference import (
    AGENT_INACTIVE,
    AGENT_NOT_ACCESSIBLE,
    AGENT_OUT_OF_SCOPE,
)
from app.services.flow_orchestration.runner import execute_flow_version
from tests.flow_agent_step_support import _admin_and_project, _agent, _flow, _node_run, _provider_double


def _agent_definition(agent_id: str) -> dict:
    return {
        "schema_version": "2.0",
        "nodes": [
            {"id": "start", "type": "trigger", "config": {"trigger_type": "manual"}},
            {"id": "summarise", "type": "agent_step", "config": {"agent_definition_id": agent_id, "prompt": "Sum."}},
            {"id": "end", "type": "output"},
        ],
        "edges": [
            {"source_node_id": "start", "target_node_id": "summarise"},
            {"source_node_id": "summarise", "target_node_id": "end"},
        ],
    }


@pytest.mark.asyncio
async def test_validate_checks_agent_references_only_against_an_explicit_context(client, auth_headers, db):
    admin, project = await _admin_and_project(db)
    scoped = await _agent(db, admin.id, project_id=project.id)
    await db.commit()
    definition = _agent_definition(scoped.id)

    async def codes(body: dict) -> list[str]:
        response = await client.post("/api/v1/flows/validate", json=body, headers=auth_headers)
        assert response.status_code == 200, response.text
        return [error["code"] for error in response.json().get("errors", [])]

    assert "agent_reference_context_required" in await codes({"definition": definition})
    assert AGENT_OUT_OF_SCOPE in await codes({"definition": definition, "project_id": None})
    agent_codes = {AGENT_OUT_OF_SCOPE, AGENT_INACTIVE, AGENT_NOT_ACCESSIBLE, "agent_reference_context_required"}
    assert not agent_codes & set(await codes({"definition": definition, "project_id": project.id}))
    version = await _flow(db, admin, None, {"agent_definition_id": scoped.id, "prompt": "Sum."})
    flow_id = (await db.get(FlowDefinitionVersion, version.id)).flow_id
    await db.commit()
    assert AGENT_OUT_OF_SCOPE in await codes({"definition": definition, "flow_id": flow_id})


@pytest.mark.asyncio
async def test_published_execution_mode_without_a_published_revision_is_an_explicit_configuration_state(
    db, monkeypatch
):
    from app.services.agent_definition_execution_states import AGENT_DEFINITION_EXECUTION_MODE_KEY
    from app.services.flow_orchestration.flow_agent_reference import flow_agent_reference_errors
    from app.services.system_config.values import set_system_config_value

    admin, project = await _admin_and_project(db)
    agent = await _agent(db, admin.id, project_id=project.id)
    await set_system_config_value(db, key=AGENT_DEFINITION_EXECUTION_MODE_KEY, value="published", description="test")
    await db.flush()
    calls = _provider_double(monkeypatch)

    errors = await flow_agent_reference_errors(db, _agent_definition(agent.id), user_id=admin.id, project_id=project.id)
    assert [error["code"] for error in errors] == ["agent_needs_publication"]
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Sum."})
    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "x"}
    )
    assert run.status == "failed" and calls == []
    assert (await _node_run(db, run, "summarise")).error.startswith("agent_needs_publication")


@pytest.mark.asyncio
async def test_a_turn_past_the_flow_run_time_limit_is_cancelled_and_fails_the_node(db, monkeypatch):
    import asyncio

    admin, project = await _admin_and_project(db)
    agent = await _agent(db, admin.id, project_id=project.id)
    cancelled: list[bool] = []

    async def runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def slow_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return {"content": "late", "tool_calls": None, "model": "m", "usage": {}}, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", slow_chat)
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Sum."})
    version.runtime_settings = {"max_run_seconds": 1}
    await db.flush()

    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "x"}
    )

    assert run.status == "failed" and cancelled == [True]
    node = await _node_run(db, run, "summarise")
    assert node.status == "failed"
    child = await db.get(Session, run.child_session_ids_json[0])
    assert child.status == "error" and child.ended_at is not None
    assert child.metadata_["flow_agent_step_outcome"] == "flow_run_timeout_exceeded"
    assert (
        await db.execute(
            select(FlowNodeRun).where(FlowNodeRun.orchestrator_run_id == run.id, FlowNodeRun.node_id == "end")
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_oversized_step_input_is_refused_before_any_session_or_model_call(db, monkeypatch):
    from app.services.flow_orchestration.flow_agent_step import MAX_INPUT_CHARS

    admin, project = await _admin_and_project(db)
    agent = await _agent(db, admin.id, project_id=project.id)
    calls = _provider_double(monkeypatch)
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Sum."})

    run = await execute_flow_version(
        db,
        flow_version_id=version.id,
        project_id=project.id,
        user_id=admin.id,
        initial_input={"request": "x" * (MAX_INPUT_CHARS + 10)},
    )

    assert run.status == "failed" and calls == []
    assert not run.child_session_ids_json
    assert (await _node_run(db, run, "summarise")).error.startswith("agent_step_input_too_large")


@pytest.mark.asyncio
async def test_a_failed_turn_leaves_its_child_session_terminal(db, monkeypatch):
    admin, project = await _admin_and_project(db)
    agent = await _agent(db, admin.id, project_id=project.id)
    _provider_double(monkeypatch, raise_error=RuntimeError("provider unavailable"))
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Sum."})

    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "x"}
    )

    child = await db.get(Session, run.child_session_ids_json[0])
    assert run.status == "failed" and child.status == "error" and child.ended_at is not None
