"""Shared helpers for the test_flow_agent_step_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

import app.agent.engine as engine_module
from app.models import AgentDefinition, FlowDefinition, FlowDefinitionVersion, FlowNodeRun, Project, User

ANSWER = "Incident summary: demo service unavailable for two minutes, recovered automatically."


def uid() -> str:
    return str(uuid.uuid4())


async def _admin_and_project(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    return admin, project


async def _agent(db, owner_id: str, *, project_id: str | None = None, active: bool = True) -> AgentDefinition:
    agent = AgentDefinition(
        id=uid(),
        owner_id=owner_id,
        project_id=project_id,
        name=f"Summariser {uid()[:8]}",
        agent_type="diagnosis",
        system_prompt="Summarise the incident in one sentence.",
        is_active=active,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _flow(db, admin, project_id: str | None, agent_config: dict, node_type: str = "agent_step"):
    flow = FlowDefinition(
        id=uid(),
        key=f"agent-flow-{uid()}",
        name="Agent flow",
        project_id=project_id,
        status="draft",
        is_active=True,
        created_by=admin.id,
    )
    definition = {
        "schema_version": "2.0",
        "nodes": [
            {"id": "start", "type": "trigger", "config": {"trigger_type": "manual"}},
            {"id": "summarise", "type": node_type, "config": agent_config},
            {"id": "end", "type": "output"},
        ],
        "edges": [
            {"source_node_id": "start", "target_node_id": "summarise"},
            {"source_node_id": "summarise", "target_node_id": "end"},
        ],
    }
    db.add(flow)
    await db.flush()
    version = FlowDefinitionVersion(
        id=uid(), flow_id=flow.id, version=1, status="draft", definition_json=definition, created_by=admin.id
    )
    db.add(version)
    await db.flush()
    return version


def _provider_double(monkeypatch, *, answer: str | None = ANSWER, raise_error: Exception | None = None):
    calls: list[list[dict]] = []

    async def runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        calls.append(messages)
        if raise_error is not None:
            raise raise_error
        return {
            "content": answer,
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 20, "completion_tokens": 12, "total_tokens": 32},
        }, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", chat)
    return calls


async def _node_run(db, run, node_id: str) -> FlowNodeRun:
    return (
        await db.execute(
            select(FlowNodeRun).where(FlowNodeRun.orchestrator_run_id == run.id, FlowNodeRun.node_id == node_id)
        )
    ).scalar_one()
