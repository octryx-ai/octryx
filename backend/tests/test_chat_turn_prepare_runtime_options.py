"""Workspace runtime options, thread runtime reuse, unassigned explicit agents and SQLite lock retries."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import app.services.session.turn_prepare as turn_prepare_module
from app.models import AgentDefinition, ControlPlaneRuntimeTarget, Project, User, WorkspacePolicy
from app.models import Session as AgentSession
from app.services.runtime_options import list_chat_runtime_options
from app.services.session.turn_request import TurnRequest
from app.services.session.turn_start import prepare_turn
from app.services.workspace_composition import seed_workspace_bundle_foundation
from tests.turn_preparation_support import prepare_chat_turn


@pytest.mark.asyncio
async def test_chat_runtime_options_honor_selected_only_workspace_policy(db):
    allowed_runtime = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    assert allowed_runtime is not None
    blocked_runtime = ControlPlaneRuntimeTarget(
        id=str(uuid.uuid4()),
        config_id=allowed_runtime.config_id,
        provider_id=allowed_runtime.provider_id,
        model_id="blocked-runtime-model",
        priority=allowed_runtime.priority + 10,
        is_active=True,
    )
    db.add(blocked_runtime)
    await db.commit()

    workspace_execution_view = {
        "workspace_id": str(uuid.uuid4()),
        "runtime_policy": {"runtime_assignment_mode": "selected_only"},
        "bindings_by_kind": {
            "runtime": [
                {
                    "binding_key": f"runtime-target:{allowed_runtime.id}",
                    "source_entity_id": allowed_runtime.id,
                    "is_enabled": True,
                    "binding_status": "active",
                }
            ]
        },
    }

    options = await list_chat_runtime_options(
        db,
        workspace_execution_view=workspace_execution_view,
        include_runtime_target_id=blocked_runtime.id,
    )

    option_ids = [option["value"] for option in options]
    assert "" not in option_ids
    assert allowed_runtime.id in option_ids
    assert blocked_runtime.id in option_ids
    blocked_option = next(option for option in options if option["value"] == blocked_runtime.id)
    assert blocked_option["disabled"] is True
    assert "not allowed" in blocked_option["disabled_reason"]


@pytest.mark.asyncio
async def test_prepare_chat_turn_reuses_the_threads_runtime(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    sticky_runtime = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    assert sticky_runtime is not None
    auto_runtime = ControlPlaneRuntimeTarget(
        id=str(uuid.uuid4()),
        config_id=sticky_runtime.config_id,
        provider_id=sticky_runtime.provider_id,
        model_id="anthropic.claude-sonnet-4-6",
        priority=99,
        is_active=True,
    )
    project = Project(id=str(uuid.uuid4()), name="sticky-runtime-project", config={}, is_active=True)
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"runtime_target_id": sticky_runtime.id, "runtime_label": "Sticky Runtime",
                   "runtime_selection_source": "explicit"},
    )
    db.add_all([auto_runtime, project, session])
    await db.commit()


    prepared_session, selected_runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        session_id=session.id,
        prompt="Large validation run: inspect AWS CodePipeline in eu-central-1.",
        project_id=project.id,
        agent_type="diagnosis",
    )

    assert prepared_session.id == session.id
    assert selected_runtime_target_id == sticky_runtime.id
    assert prepared_session.metadata_["runtime_target_id"] == sticky_runtime.id
    assert prepared_session.metadata_["runtime_selection_source"] == "session"


@pytest.mark.asyncio
async def test_prepare_chat_turn_selected_only_agent_rejects_explicit_unassigned_agent(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="selected-agent-explicit-project", config={}, is_active=True)
    db.add(project)
    await db.commit()

    await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    policy = (await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == project.id))).scalar_one()
    policy.routing_policy = {"agent_assignment_mode": "selected_only"}
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Unassigned Project Agent",
        description="Not part of the selected project bindings.",
        goal="Handle explicit requests.",
        agent_type="change",
        is_active=True,
    )
    db.add(agent)
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await prepare_chat_turn(
            db=db,
            user=admin,
            prompt="Use the explicit agent for this task.",
            project_id=project.id,
            agent_id=agent.id,
            agent_type="change",
        )

    assert exc_info.value.status_code == 403
    assert "agent" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_prepare_chat_turn_with_retry_recovers_from_sqlite_lock(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    calls = {"count": 0}

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    async def fake_prepare_turn_in_session(_db, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError("INSERT INTO sessions", {}, Exception("database is locked"))
        return SimpleNamespace(session_id="retry-session")

    monkeypatch.setattr(turn_prepare_module, "prepare_turn_in_session", fake_prepare_turn_in_session)

    prepared = await prepare_turn(
        TurnRequest(user_id=admin.id, prompt="Investigate report-builder presentation"),
        session_factory=fake_session_factory,
    )

    assert calls["count"] == 2
    assert prepared.session_id == "retry-session"
