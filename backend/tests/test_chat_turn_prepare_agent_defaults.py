"""The workspace default agent for document turns, explicit agent types and explicit start contracts."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AgentDefinition, ControlPlaneRuntimeTarget, Project, User
from app.services.workspace_composition import seed_workspace_bundle_foundation
from tests.turn_preparation_support import prepare_chat_turn


@pytest.mark.asyncio
async def test_prepare_chat_turn_applies_only_the_workspace_default_agent_to_a_document_turn(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    runtime_target = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    assert runtime_target is not None

    project = Project(
        id=str(uuid.uuid4()),
        name=f"workspace-doc-default-{uuid.uuid4()}",
        config={},
        is_active=True,
    )
    db.add(project)
    await db.flush()

    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        runtime_target_id=runtime_target.id,
        name="Documentation Workspace Agent",
        description="Creates structured documents.",
        goal="Produce concise document outputs.",
        agent_type="documentation",
        thinking_level="deep",
        is_active=True,
    )
    project.config = {
        "project_agent_preferences": {
            agent.id: {"status": "primary"},
        },
    }
    db.add(agent)
    await db.commit()

    await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    project.config = {}
    db.add(project)
    await db.commit()

    session, runtime_target_id, thinking_level, agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Create a concise Word report summarizing the quarterly enablement plan.",
        project_id=project.id,
        agent_type="chat",
    )

    # The default agent is the governed default.
    assert session.metadata_["agent_definition_id"] == agent.id
    assert session.metadata_["agent_selection_source"] == "default"
    assert runtime_target_id == runtime_target.id
    assert thinking_level == "deep"
    assert agent_payload is not None and agent_payload["id"] == agent.id


@pytest.mark.asyncio
async def test_prepare_chat_turn_explicit_agent_type_skips_the_workspace_default_agent(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    project = Project(
        id=str(uuid.uuid4()),
        name=f"workspace-doc-guard-{uuid.uuid4()}",
        config={},
        is_active=True,
    )
    db.add(project)
    await db.flush()

    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Delivery Workspace Agent",
        description="Coordinates release work.",
        goal="Plan delivery work.",
        agent_type="change",
        is_active=True,
    )
    project.config = {
        "project_agent_preferences": {
            agent.id: {"status": "primary"},
        }
    }
    db.add(agent)
    await db.commit()

    await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    project.config = {}
    db.add(project)
    await db.commit()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Create a concise Word report about ticketing API integration risks.",
        project_id=project.id,
        agent_type="chat",
        agent_type_explicit=True,
    )

    assert session.agent_type == "chat"
    # Explicit-first default: no documentation-keyword intent; the caller's explicit
    # agent type keeps the Workspace default agent out.
    assert session.metadata_["routing_intent"] == "diagnosis"
    assert session.metadata_["agent_key"] == "assistant"  # the platform Assistant
    assert session.metadata_["agent_selection_source"] == "platform_default"
    assert "playbook_instance_id" not in session.metadata_


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_chat_turn_preserves_explicit_start_contract_over_agent_defaults(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    legacy_project = Project(id=str(uuid.uuid4()), name="legacy-agent-project", config={}, is_active=True)
    explicit_project = Project(id=str(uuid.uuid4()), name="explicit-start-project", config={}, is_active=True)
    db.add_all([legacy_project, explicit_project])
    await db.flush()

    explicit_runtime_target = (
        (await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.is_active.is_(True))))
        .scalars()
        .first()
    )
    assert explicit_runtime_target is not None

    # A global agent: a turn in the explicit Workspace may run it; its sticky defaults must not win.
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=None,
        name="Legacy Document Agent",
        description="Legacy agent with sticky defaults.",
        goal="Update documents from legacy project defaults.",
        agent_type="change",
        runtime_target_id=explicit_runtime_target.id,
        thinking_level="deep",
        is_active=True,
    )
    db.add(agent)
    await db.commit()

    session, selected_runtime_target_id, selected_thinking_level, agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Create a concise research document.",
        project_id=explicit_project.id,
        runtime_target_id=explicit_runtime_target.id,
        agent_id=agent.id,
        agent_type="documentation",
        agent_type_explicit=True,
        project_id_explicit=True,
        runtime_target_id_explicit=True,
        thinking_level="light",
        thinking_level_explicit=True,
    )

    assert session.project_id == explicit_project.id
    assert session.agent_type == "documentation"
    assert selected_runtime_target_id == explicit_runtime_target.id
    assert selected_thinking_level == "light"
    assert session.metadata_["runtime_target_id"] == explicit_runtime_target.id
    assert session.metadata_["thinking_level"] == "light"
    assert session.metadata_["agent_definition_id"] == agent.id
    assert agent_payload is not None
    assert agent_payload["id"] == agent.id

    # Another Workspace's agent never runs in this Workspace's turn.
    foreign = AgentDefinition(
        id=str(uuid.uuid4()), owner_id=admin.id, project_id=legacy_project.id, name="Legacy Workspace Agent",
        agent_type="change", is_active=True,
    )
    db.add(foreign)
    await db.commit()
    with pytest.raises(HTTPException) as refused:
        await prepare_chat_turn(
            db=db, user=admin, prompt="Create a concise research document.", project_id=explicit_project.id,
            agent_id=foreign.id, project_id_explicit=True,
        )
    assert refused.value.status_code == 404
