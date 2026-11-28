"""Read-only chat agent guidance: identities, visibility and declared surface."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as AgentSession
from app.services.agent_definition_execution_states import AGENT_DEFINITION_EXECUTION_MODE_KEY
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from app.services.session.chat_agent_guidance import CHAT_AGENT_GUIDANCE_KEY, project_chat_agent_guidance
from app.services.system_config.values import set_system_config_value
from app.web._helpers._chat_state_builder import _build_chat_state
from app.web._helpers.chat_turn_ack_state import _build_chat_turn_ack_state
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_project, make_user


async def _set_mode(db: AsyncSession, value: str) -> None:
    await set_system_config_value(
        db, key=AGENT_DEFINITION_EXECUTION_MODE_KEY, value=value, description="Agent definition execution mode (test)"
    )
    await db.flush()


async def _session(db: AsyncSession, *, user_id: str, metadata: dict) -> AgentSession:
    session = AgentSession(
        id=str(uuid.uuid4()), user_id=user_id, agent_type="chat", status="completed", metadata_=dict(metadata)
    )
    db.add(session)
    await db.flush()
    return session


@pytest.mark.asyncio
async def test_a_mention_keeps_the_bound_agent_next_and_reports_the_latest_turn_separately(db: AsyncSession):
    admin = await admin_user(db)
    bound = await make_definition(db, owner=admin, name="Bound Agent", steps=0)
    mentioned = await make_definition(db, owner=admin, name="Mentioned Agent", steps=0)
    session = await _session(
        db,
        user_id=admin.id,
        metadata={
            "bound_agent_definition_id": bound.id,
            "agent_definition_id": mentioned.id,
            "agent_selection_source": "mention",
        },
    )

    guidance = await project_chat_agent_guidance(db, user_id=admin.id, session=session)

    assert guidance["sessionId"] == session.id
    assert guidance["nextTurnAgent"] == {"id": bound.id, "name": "Bound Agent", "availability": "available"}
    assert guidance["nextTurnAgentSource"] == "session_binding"
    assert guidance["lastTurnAgent"] == {"id": mentioned.id, "name": "Mentioned Agent", "availability": "available"}
    assert guidance["lastTurnSelectionSource"] == "mention"


@pytest.mark.asyncio
async def test_a_session_without_a_binding_is_unbound_even_with_a_last_agent(db: AsyncSession):
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, name="Legacy Agent", steps=0)
    empty = await _session(db, user_id=admin.id, metadata={"bound_agent_definition_id": None, "agent_definition_id": agent.id})
    legacy = await _session(db, user_id=admin.id, metadata={"agent_definition_id": agent.id})

    unbound = await project_chat_agent_guidance(db, user_id=admin.id, session=empty)
    assert unbound["nextTurnAgent"] is None
    assert unbound["nextTurnAgentSource"] == "none"
    # Unbound is not "no tools": a Workspace default may still apply and is not predicted.
    assert unbound["toolSurface"] == "unknown"
    assert unbound["lastTurnAgent"]["id"] == agent.id

    unkeyed = await project_chat_agent_guidance(db, user_id=admin.id, session=legacy)
    assert unkeyed["nextTurnAgent"] is None
    assert unkeyed["nextTurnAgentSource"] == "none"


@pytest.mark.asyncio
async def test_foreign_and_deleted_agents_are_indistinguishable_and_disclose_nothing(db: AsyncSession):
    # "Foreign" is an agent of a Workspace the (non-admin) user is not a member of.
    viewer = await make_user(db, label="guidance-viewer")
    other = await make_user(db, label="guidance-other")
    foreign = await make_definition(
        db, owner=other, name="Foreign Secret Agent", steps=0, project_id=(await make_project(db)).id
    )
    deleted_id = str(uuid.uuid4())
    foreign_session = await _session(db, user_id=viewer.id, metadata={"bound_agent_definition_id": foreign.id})
    deleted_session = await _session(db, user_id=viewer.id, metadata={"bound_agent_definition_id": deleted_id})

    foreign_guidance = await project_chat_agent_guidance(db, user_id=viewer.id, session=foreign_session)
    deleted_guidance = await project_chat_agent_guidance(db, user_id=viewer.id, session=deleted_session)

    assert foreign_guidance["nextTurnAgent"] == {"id": foreign.id, "name": None, "availability": "unavailable"}
    assert deleted_guidance["nextTurnAgent"] == {"id": deleted_id, "name": None, "availability": "unavailable"}
    for guidance in (foreign_guidance, deleted_guidance):
        assert (guidance["toolSurface"], guidance["contentSource"]) == ("unknown", "unknown")
    assert "Foreign Secret Agent" not in repr(foreign_guidance)


@pytest.mark.asyncio
async def test_an_owned_inactive_agent_is_named_as_inactive_without_a_surface(db: AsyncSession):
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, name="Paused Agent", steps=0)
    agent.is_active = False
    agent.tool_surface = "none"
    session = await _session(db, user_id=admin.id, metadata={"bound_agent_definition_id": agent.id})

    guidance = await project_chat_agent_guidance(db, user_id=admin.id, session=session)

    assert guidance["nextTurnAgent"] == {"id": agent.id, "name": "Paused Agent", "availability": "inactive"}
    assert guidance["toolSurface"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(("stored", "shown"), [("none", "none"), ("governed", "governed"), ("", "unknown")])
async def test_draft_mode_reports_the_live_rows_declared_surface(db: AsyncSession, stored: str, shown: str):
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, steps=0)
    agent.tool_surface = stored
    session = await _session(db, user_id=admin.id, metadata={"bound_agent_definition_id": agent.id})

    guidance = await project_chat_agent_guidance(db, user_id=admin.id, session=session)

    assert (guidance["toolSurface"], guidance["contentSource"]) == (shown, "live_draft_row")


@pytest.mark.asyncio
async def test_published_mode_reports_the_published_snapshot_not_the_live_draft(db: AsyncSession):
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, steps=0)
    agent.tool_surface = "none"
    await db.flush()
    revision = await create_draft_revision(db, definition=agent, created_by=admin.id)
    await publish_revision(db, revision=revision, published_by=admin.id)
    agent.tool_surface = "governed"
    await _set_mode(db, "published")
    session = await _session(db, user_id=admin.id, metadata={"bound_agent_definition_id": agent.id})

    guidance = await project_chat_agent_guidance(db, user_id=admin.id, session=session)

    assert (guidance["toolSurface"], guidance["contentSource"]) == ("none", "published_revision")


@pytest.mark.asyncio
async def test_published_mode_without_a_revision_and_an_invalid_mode_stay_unknown(db: AsyncSession):
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, steps=0)
    session = await _session(db, user_id=admin.id, metadata={"bound_agent_definition_id": agent.id})

    await _set_mode(db, "published")
    unpublished = await project_chat_agent_guidance(db, user_id=admin.id, session=session)
    assert (unpublished["toolSurface"], unpublished["contentSource"]) == ("unknown", "needs_publication")

    await _set_mode(db, "publsihed")
    misconfigured = await project_chat_agent_guidance(db, user_id=admin.id, session=session)
    assert (misconfigured["toolSurface"], misconfigured["contentSource"]) == ("unknown", "unknown")


@pytest.mark.asyncio
async def test_a_new_chat_launched_for_an_agent_reports_the_launch_request(db: AsyncSession):
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, name="Launch Agent", steps=0)
    agent.tool_surface = "none"

    guidance = await project_chat_agent_guidance(db, user_id=admin.id, session=None, requested_agent_id=agent.id)

    assert guidance["sessionId"] is None
    assert guidance["nextTurnAgentSource"] == "launch_request"
    assert guidance["nextTurnAgent"]["name"] == "Launch Agent"
    assert guidance["lastTurnAgent"] is None
    assert guidance["toolSurface"] == "none"


@pytest.mark.asyncio
async def test_bootstrap_and_turn_response_carry_the_same_guidance_and_current_name(db: AsyncSession):
    admin = await admin_user(db)
    bound = await make_definition(db, owner=admin, name="Bound Agent", steps=0)
    bound.tool_surface = "none"
    latest = await make_definition(db, owner=admin, name="Renamed Agent", steps=0)
    session = await _session(
        db,
        user_id=admin.id,
        metadata={
            "bound_agent_definition_id": bound.id,
            "agent_definition_id": latest.id,
            "agent_name": "Name At Turn Time",
            "agent_selection_source": "mention",
        },
    )
    await db.commit()

    bootstrap = await _build_chat_state(None, db, user=admin, session_id=session.id)
    ack = await _build_chat_turn_ack_state(
        None, db, user=admin, session=session, runtime_target_id="", thinking_level="light", agent_id="", agent_type=""
    )

    assert bootstrap[CHAT_AGENT_GUIDANCE_KEY] == ack[CHAT_AGENT_GUIDANCE_KEY]
    assert ack[CHAT_AGENT_GUIDANCE_KEY]["nextTurnAgent"]["id"] == bound.id
    assert ack[CHAT_AGENT_GUIDANCE_KEY]["toolSurface"] == "none"
    # Ack name parity: the owner-scoped current name, as on reload, not the persisted one.
    assert bootstrap["selectedAgentName"] == ack["selectedAgentName"] == "Renamed Agent"
    assert ack["selectedSession"]["agentName"] == "Renamed Agent"


@pytest.mark.asyncio
async def test_turn_response_withholds_the_persisted_name_of_a_deleted_agent(db: AsyncSession):
    admin = await admin_user(db)
    session = await _session(
        db,
        user_id=admin.id,
        metadata={"agent_definition_id": str(uuid.uuid4()), "agent_name": "Gone Agent"},
    )
    await db.commit()

    ack = await _build_chat_turn_ack_state(
        None, db, user=admin, session=session, runtime_target_id="", thinking_level="light", agent_id="", agent_type=""
    )

    assert ack["selectedAgentName"] == ""
    assert ack[CHAT_AGENT_GUIDANCE_KEY]["lastTurnAgent"]["availability"] == "unavailable"
    assert "Gone Agent" not in repr(ack[CHAT_AGENT_GUIDANCE_KEY])


@pytest.mark.asyncio
async def test_a_new_thread_bootstrap_carries_guidance_without_a_session(db: AsyncSession):
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin, name="Test In Chat Agent", steps=0)
    await db.commit()

    state = await _build_chat_state(None, db, user=admin, agent_id=agent.id, new_thread=True)

    guidance = state[CHAT_AGENT_GUIDANCE_KEY]
    assert guidance["sessionId"] is None
    assert guidance["nextTurnAgent"]["id"] == agent.id
    assert guidance["nextTurnAgentSource"] == "launch_request"
