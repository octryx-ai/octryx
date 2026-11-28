"""Agent selection for operations and diagnosis prompts and agent definition resolution in published mode."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AgentDefinition, Project, User
from app.models import Session as AgentSession
from tests.turn_preparation_support import prepare_chat_turn


async def _selected_agent(db, *, name: str) -> AgentDefinition:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        name=name,
        description="Chat turn resolution fixture",
        goal="Answer the request",
        agent_type="diagnosis",
        thinking_level="light",
        branch_prefix="octryx",
        system_prompt="Be precise.",
        output_prompt="Report findings.",
        is_active=True,
    )
    agent.skill_preferences = {}
    db.add(agent)
    await db.commit()
    return agent


@pytest.mark.asyncio
async def test_prepare_chat_turn_operations_prompt_selects_no_agent_by_prompt(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="ops-over-coding-project", config={}, is_active=True)
    db.add(project)
    await db.flush()

    coding_agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Coding Delivery Agent",
        description="Delivers coding work, API changes, implementation and verification.",
        goal="Implement code safely.",
        agent_type="change",
        thinking_level="deep",
        is_active=True,
    )
    sre_agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="SRE Investigator Agent",
        description="Investigates AWS, EKS, Kubernetes, deployments, and runtime operations.",
        goal="Diagnose operational state from live evidence.",
        agent_type="diagnosis",
        thinking_level="deep",
        is_active=True,
    )
    db.add_all([coding_agent, sre_agent])
    await db.commit()

    session, _runtime_target_id, _thinking_level, agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Use AWS EKS evidence to verify the runtime identity and deployment state.",
        project_id=project.id,
        agent_type="diagnosis",
    )

    # Neither agent is picked from the prompt text: the platform default runs the turn.
    assert agent_payload["builtinKey"] == "assistant"
    assert (session.metadata_ or {}).get("agent_key") == "assistant"
    assert (session.metadata_ or {}).get("agent_selection_source") == "platform_default"
    assert (session.metadata_ or {}).get("routing_intent") == "diagnosis"
    assert (session.metadata_ or {}).get("execution_strategy_reason") == "strategy:direct_default"


@pytest.mark.asyncio
async def test_prepare_chat_turn_does_not_auto_select_change_agent_for_diagnosis_prompt(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="diagnosis-stays-diagnosis-project", config={}, is_active=True)
    db.add(project)
    await db.flush()

    coding_agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Coding Delivery Agent",
        description="Delivers coding work, API changes, implementation and verification.",
        goal="Implement code safely.",
        agent_type="change",
        thinking_level="deep",
        is_active=True,
    )
    db.add(coding_agent)
    await db.commit()

    session, _runtime_target_id, _thinking_level, agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="AWS identity check. Call aws_read_operation and return the account.",
        project_id=project.id,
        agent_type="diagnosis",
    )

    assert agent_payload["builtinKey"] == "assistant"
    assert (session.metadata_ or {}).get("agent_key") == "assistant"
    assert session.agent_type in {"chat", "diagnosis"}


@pytest.mark.asyncio
async def test_prepare_chat_turn_does_not_reuse_change_agent_for_a_later_operations_phase(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="ops-existing-session-project", config={}, is_active=True)
    db.add(project)
    await db.flush()

    coding_agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Coding Delivery Agent",
        description="Delivers coding work and implementation.",
        goal="Implement code safely.",
        agent_type="change",
        thinking_level="deep",
        is_active=True,
    )
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={
            "agent_definition_id": coding_agent.id,
            "agent_name": coding_agent.name,
            "routing_intent": "coding",
        },
    )
    db.add_all([coding_agent, session])
    await db.commit()

    async def operations_phase(_db, _session, *, user_message):
        return {
            "source": "db",
            "status": "matched",
            "selection_source": "workflow_run",
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request",
            "workflow_contract": {"workflow_id": "knowledge_request", "routing_intent": "operations"},
            "tool_policy": {},
            "safety_constraints": {},
        }

    monkeypatch.setattr("app.services.session.turn_routing_resolution.run_turn_resolution", operations_phase)

    prepared, _runtime_target_id, _thinking_level, agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        session_id=session.id,
        prompt="Use AWS evidence to list the CodePipeline pipelines in eu-central-1. Do not change anything.",
        project_id=project.id,
        agent_type="diagnosis",
    )

    # The earlier coding turn's change agent is not carried into the read-only phase.
    assert agent_payload["builtinKey"] == "assistant"
    assert prepared.id == session.id
    assert prepared.agent_type in {"chat", "diagnosis"}
    assert (prepared.metadata_ or {}).get("routing_intent") == "operations"
    assert (prepared.metadata_ or {}).get("agent_key") == "assistant"


@pytest.mark.asyncio
async def test_prepare_chat_turn_records_the_agent_definition_resolution(db):
    from app.services.agent_definition_execution_states import RESOLUTION_METADATA_KEY, SOURCE_LIVE_DRAFT_ROW

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    agent = await _selected_agent(db, name="Draft Resolution Agent")

    session, _runtime_target_id, _thinking_level, agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Please analyse the current state.",
        agent_id=agent.id,
        agent_type="diagnosis",
    )

    recorded = session.metadata_[RESOLUTION_METADATA_KEY]
    assert recorded["definition_id"] == agent.id
    assert recorded["mode"] == "draft"
    assert recorded["source"] == SOURCE_LIVE_DRAFT_ROW
    assert recorded["revision_id"] is None
    assert agent_payload is not None
    # Identifiers and states only: the authored prompt stays out of session metadata.
    assert "Be precise." not in str(recorded)


@pytest.mark.asyncio
async def test_prepare_chat_turn_refuses_an_unpublished_agent_in_published_mode(db):
    from app.services.agent_definition_execution_states import (
        AGENT_DEFINITION_EXECUTION_MODE_KEY,
        EXECUTION_MODE_PUBLISHED,
        NOT_PUBLISHED_ERROR_CODE,
    )
    from app.services.system_config.values import set_system_config_value

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    agent = await _selected_agent(db, name="Unpublished Chat Agent")
    await set_system_config_value(
        db,
        key=AGENT_DEFINITION_EXECUTION_MODE_KEY,
        value=EXECUTION_MODE_PUBLISHED,
        description="Agent definition execution mode (test)",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await prepare_chat_turn(
            db=db,
            user=admin,
            prompt="Please analyse the current state.",
            agent_id=agent.id,
            agent_type="diagnosis",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == NOT_PUBLISHED_ERROR_CODE
    assert exc_info.value.detail["definition_id"] == agent.id
