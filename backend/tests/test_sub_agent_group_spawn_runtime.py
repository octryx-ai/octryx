"""The workspace capability slice reaches children, and children run automatically when the parent runtime is unset."""

import uuid

import pytest
from sqlalchemy import select

from app.models import LLMProvider, Session, User
from app.services.control_plane_service import upsert_runtime_target
from app.tools.context import ToolContext
from app.tools.sub_agent import SpawnSubAgentTool


def _workspace_execution_view() -> dict:
    return {
        "workspace_id": "workspace-1",
        "default_binding_keys": {"runtime": "runtime-default"},
        "bindings_by_kind": {
            "runtime": [
                {
                    "binding_key": "runtime-default",
                    "capability_kind": "runtime",
                    "display_name": "Runtime Default",
                    "source_entity_id": "runtime-1",
                }
            ],
            "agent": [
                {
                    "binding_key": "agent-documentation",
                    "capability_kind": "agent",
                    "display_name": "Documentation Agent",
                    "source_entity_id": "agent-doc",
                    "agent_type": "documentation",
                },
                {
                    "binding_key": "agent-change",
                    "capability_kind": "agent",
                    "display_name": "Change Agent",
                    "source_entity_id": "agent-change",
                    "agent_type": "change",
                },
            ],
        },
    }


async def _child_sessions(db, parent_session_id: str) -> list[Session]:
    return (
        (
            await db.execute(
                select(Session).where(Session.parent_session_id == parent_session_id).order_by(Session.started_at.asc())
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_spawn_sub_agent_applies_workspace_capability_slice_to_children(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="documentation",
        metadata_={"title": "Parent workspace orchestration"},
    )
    db.add(parent_session)
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    workspace_execution_view = _workspace_execution_view()

    tool = SpawnSubAgentTool()
    await tool.execute(
        {
            "sub_tasks": ["Research benefits"],
            "inherit_agent_definition": False,
            "child_agent_type": "documentation",
        },
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={
                "project_id": "workspace-1",
                "workspace_execution_view": workspace_execution_view,
            },
            db=db,
            system_context={},
            capability_type="documentation",
            agent_mode_key="documentation",
            turn_context_snapshot={"thinking_level": "deep"},
            agent_definition={"agentType": "documentation", "id": "agent-doc"},
        ),
    )

    child_sessions = await _child_sessions(db, parent_session.id)

    assert len(child_sessions) == 1
    child_view = child_sessions[0].metadata_["workspace_execution_view"]
    assert sorted(child_view["bindings_by_kind"].keys()) == ["agent", "runtime"]
    assert [item["binding_key"] for item in child_view["bindings_by_kind"]["agent"]] == ["agent-documentation"]
    assert [item["binding_key"] for item in child_view["bindings_by_kind"]["runtime"]] == ["runtime-default"]
    assert launch_calls and launch_calls[0]["runtime_target_id"] == "runtime-1"
    assert launch_calls[0]["agent_type"] == "documentation"


async def _seed_local_and_documentation_targets(db):
    local_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="ollama",
        driver="ollama",
        display_name="Local Gemma",
        default_model_id="gemma4:e4b",
        is_global=True,
        is_active=True,
    )
    documentation_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Documentation Runtime",
        default_model_id="claude-haiku-4.5",
        is_global=True,
        is_active=True,
    )
    db.add_all([local_provider, documentation_provider])
    await db.flush()

    local_target = await upsert_runtime_target(
        db,
        provider=local_provider,
        model_id="gemma4:e4b",
        make_primary=True,
        is_active=True,
    )
    documentation_target = await upsert_runtime_target(
        db,
        provider=documentation_provider,
        model_id="claude-haiku-4.5",
        make_primary=False,
        is_active=True,
    )
    return local_target, documentation_target


@pytest.mark.asyncio
async def test_spawn_sub_agent_runs_automatically_when_parent_runtime_is_unset(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        agent_type="documentation",
        metadata_={"title": "Parent runtime fallback orchestration"},
    )
    db.add(parent_session)

    local_target, documentation_target = await _seed_local_and_documentation_targets(db)
    documentation_target.use_case_tags = ["documentation", "fast"]
    await db.commit()

    launch_calls = []

    async def fake_launch_sub_agent_group(**kwargs):
        launch_calls.append(kwargs)

    monkeypatch.setattr("app.tools.sub_agent.launch_sub_agent_group", fake_launch_sub_agent_group)

    tool = SpawnSubAgentTool()
    await tool.execute(
        {
            "sub_tasks": ["Research benefits"],
            "inherit_agent_definition": False,
            "child_agent_type": "documentation",
        },
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            system_context={},
            capability_type="documentation",
            agent_mode_key="documentation",
            turn_context_snapshot={"thinking_level": "deep"},
            agent_definition={"agentType": "documentation"},
        ),
    )

    # The "documentation" use-case tag does not pick a model.
    assert launch_calls
    assert launch_calls[0]["runtime_target_id"] is None
    assert documentation_target.id and local_target.id
