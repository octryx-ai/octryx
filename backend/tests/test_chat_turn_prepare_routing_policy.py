"""Workflow routing resolutions recorded for unknown workflow keys, coding, unmatched and resume prompts."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session as AgentSession
from app.models import User
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.turn_preparation_support import prepare_chat_turn


@pytest.mark.asyncio
async def test_prepare_chat_turn_records_an_unknown_workflow_key_as_an_explicit_state(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Bitte erstelle die Uebersicht.",
        agent_type="diagnosis",
        workflow_key="aws-topology-diagram-routing",
    )

    resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
    assert resolution["source"] == "explicit_workflow_key"
    assert resolution["status"] == "unknown_key"
    assert resolution["workflow_key"] == "aws-topology-diagram-routing"
    assert resolution["workflow_id"] is None
    assert resolution["workflow_contract"] is None
    profile = session.metadata_["execution_profile"]
    assert profile["version"] == "execution_profile.v1"
    assert profile["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_prepare_chat_turn_does_not_route_explicit_coding_to_knowledge_policy(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt=(
            "You are Octryx's governed coding agent. Execute this approved Work Plan "
            "through platform tools only. Work Item: ACME-615. Title: Cleaning Terraform "
            "and Helm Config. Approved repositories and paths: aws-shop-infrastructure "
            "terraform/base/removed.txt terraform/base/memorydb-disable.txt terraform/base/irsa.tf. "
            "Do not continue the declined PR blindly; re-evaluate Terraform removed blocks and "
            "prod/nonprod config cleanup."
        ),
        agent_type="coding",
        agent_type_explicit=True,
    )

    resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
    assert session.agent_type == "coding"
    assert session.metadata_["routing_intent"] == "coding"
    assert resolution["status"] == "unmatched"
    assert resolution["workflow_id"] is None
    assert resolution["workflow_contract"] is None
    assert resolution["tool_policy"] is None


@pytest.mark.asyncio
async def test_prepare_chat_turn_records_unmatched_workflow_routing_policy_without_code_fallback(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Say hello in one short sentence.",
        agent_type="diagnosis",
    )

    resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
    assert resolution["source"] == "workflow_selection"
    assert resolution["status"] == "unmatched"
    assert resolution["fallback_reason"] is None
    assert resolution["workflow_id"] is None
    assert resolution["workflow_contract"] is None
    assert resolution["tool_policy"] is None


@pytest.mark.asyncio
async def test_prepare_chat_turn_preserves_waiting_subagent_contract_on_resume_prompt(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    existing_session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="documentation",
        status="awaiting_subagents",
        metadata_={
            "title": "Research ticketing API integration",
            "routing_intent": "documentation",
            "routing_reason": "intent:documentation_keywords",
            "execution_strategy": "coordinator",
            "execution_strategy_reason": "strategy:workflow:research_document",
            "expected_workflow_id": "research_document",
        },
    )
    db.add(existing_session)
    await db.commit()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt=(
            "All spawned sub-agents for this thread have finished. "
            "Call get_context_from_subthreads to consolidate the child sessions, then continue the parent task."
        ),
        session_id=existing_session.id,
        agent_type="documentation",
        agent_type_explicit=False,
    )

    assert session.id == existing_session.id
    assert session.agent_type == "documentation"
    assert session.metadata_["routing_intent"] == "documentation"
    assert session.metadata_["routing_reason"] == "intent:documentation_keywords"
