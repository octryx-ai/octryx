"""Which prompts keep chat mode, never pick runtimes or project defaults, and promote direct chat to neutral mode."""

import uuid

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, Project, User
from app.web._helpers.chat_turn_ack_state import _build_chat_turn_ack_state
from tests.turn_preparation_support import prepare_chat_turn


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_chat_turn_keeps_normal_entrypoint_free_of_project_default_targets(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name="Delivery Agent",
        description="Coordinates delivery work.",
        goal="Plan and coordinate delivery",
        agent_type="change",
        thinking_level="deep",
        is_active=True,
    )
    db.add(agent)
    await db.commit()

    session, runtime_target_id, thinking_level, agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Plan the upcoming release work for this project.",
        project_id=project.id,
        runtime_target_id="",
        agent_id="",
        agent_type="change",
        thinking_level="light",
    )

    # No prompt scoring: the wording of the prompt never selects the Delivery Agent.
    assert session.metadata_["agent_key"] == "assistant"  # the platform Assistant
    assert session.metadata_["agent_selection_source"] == "platform_default"
    assert session.agent_type == "change"
    assert runtime_target_id == ""
    assert thinking_level == "light"
    assert agent_payload["builtinKey"] == "assistant"

    ack_state = await _build_chat_turn_ack_state(
        None,
        db,
        user=admin,
        session=session,
        runtime_target_id="",
        thinking_level="light",
        agent_id="",
        agent_type="diagnosis",
    )
    assert ack_state["selectedAgentId"] == agent_payload["id"]  # the platform Assistant
    assert ack_state["selectedAgentType"] == "change"
    assert ack_state["selectedAgentSelectionSource"] == "platform_default"


@pytest.mark.asyncio
async def test_prepare_chat_turn_keeps_implicit_coding_prompt_in_chat_mode_by_default(db):
    # Explicit-first default: coding keywords no longer promote
    # an implicit turn to coding mode; the turn runs as a normal governed
    # chat turn.
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Create calculator.py and test_calculator.py, run pytest, and finish after verification succeeds.",
        agent_type="diagnosis",
    )

    assert session.agent_type == "chat"
    assert session.metadata_["routing_intent"] == "diagnosis"
    assert session.metadata_["routing_reason"] == "intent:diagnosis_default"


@pytest.mark.asyncio
async def test_prepare_chat_turn_never_picks_a_runtime_from_the_prompt(db):
    # A coding prompt that names a migration does not pin a coding runtime; the
    # runtime comes only from explicit sources.
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Migriere spring-petclinic-rest zu Java 25 und Spring Boot 4.0.3 mit OpenRewrite.",
        agent_type="coding",
        agent_type_explicit=True,
    )

    assert session.agent_type == "coding"
    assert runtime_target_id == ""
    assert session.metadata_["runtime_selection_source"] == "global_default"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_chat_turn_keeps_chat_mode_for_smoke_test_validation_prompt(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Smoke test the simplified composer start path.",
        agent_type="chat",
    )

    assert session.agent_type == "chat"
    assert session.metadata_["routing_intent"] == "diagnosis"
    # Explicit-first default: no keyword classification, so the turn carries
    # the plain diagnosis default instead of "intent:validation_prompt".
    assert session.metadata_["routing_reason"] == "intent:diagnosis_default"


@pytest.mark.asyncio
async def test_prepare_chat_turn_keeps_diagnosis_default_for_documentation_prompt_without_mode(db):
    # Explicit-first default: documentation keywords no longer set the intent.
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Create a concise Word report about ticketing API integration risks and benefits.",
        agent_type="chat",
    )

    assert session.agent_type == "chat"
    assert session.metadata_["routing_intent"] == "diagnosis"
    assert session.metadata_["routing_reason"] == "intent:diagnosis_default"


@pytest.mark.asyncio
async def test_prepare_chat_turn_promotes_simple_direct_chat_to_neutral_chat_mode(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Say hello in one short sentence.",
        agent_type="diagnosis",
    )

    assert session.agent_type == "chat"
    assert session.metadata_["routing_intent"] == "diagnosis"
    assert session.metadata_["routing_reason"] == "intent:diagnosis_default"
    profile = session.metadata_["execution_profile"]
    assert profile["version"] == "execution_profile.v1"
    assert profile["status"] == "allowed"
    assert profile["profile_id"] == "direct_chat_safe"
    # No pre-turn router; preparation and runtime agree on the decision source.
    assert profile["decision_source"] == "direct_chat_safe"
    assert profile["llm_router"] == {"status": "not_used"}
    assert "safety_plan" not in session.metadata_


@pytest.mark.asyncio
async def test_prepare_chat_turn_keeps_chat_mode_for_non_coding_admin_request(db):
    # Explicit-first default: the admin/knowledge keyword tail no longer
    # classifies the intent, so the implicit turn lands in neutral chat mode
    # instead of being pinned to diagnosis by keyword classification.
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        db=db,
        user=admin,
        prompt="Explain the current provider and runtime configuration for the admin panel.",
        agent_type="diagnosis",
    )

    assert session.agent_type == "chat"
    assert session.metadata_["routing_intent"] == "diagnosis"
