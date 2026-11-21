"""Independent counterprobes for inactive agents executing new Chat turns."""

import logging

import pytest
from fastapi import HTTPException

from app.services.agent_definition_execution import resolve_agent_definition_for_execution
from app.services.agent_definition_execution_outcomes import (
    AgentDefinitionExecutionError,
    execution_payload_or_none,
    require_background_execution_payload,
    require_execution_payload,
)
from app.services.agent_definition_execution_states import AGENT_DEFINITION_EXECUTION_MODE_KEY
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from app.services.session.turn_agent_selection import resolve_turn_agent_definition
from app.services.session.turn_refusals import TurnRefusalState, TurnRefusedError
from app.services.system_config.values import set_system_config_value
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_project, make_user


async def _definition_in_mode(db, mode):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, steps=0)
    if mode == "published":
        revision = await create_draft_revision(db, definition=definition, created_by=owner.id)
        await publish_revision(db, revision=revision, published_by=owner.id)
    await set_system_config_value(
        db, key=AGENT_DEFINITION_EXECUTION_MODE_KEY, value=mode, description="Judge fixture"
    )
    return owner, definition


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["draft", "published"])
@pytest.mark.parametrize("entrypoint", ["request_payload", "chat_turn"])
async def test_inactive_owned_agent_cannot_supply_new_turn_payload(db, entrypoint, mode):
    owner, definition = await _definition_in_mode(db, mode)
    definition.is_active = False
    await db.flush()

    if entrypoint == "chat_turn":
        with pytest.raises(TurnRefusedError):
            await resolve_turn_agent_definition(db, agent_id=definition.id, owner_id=owner.id)
    else:
        resolution = await resolve_agent_definition_for_execution(
            db, definition_id=definition.id, visible_to_user_id=owner.id
        )
        with pytest.raises(HTTPException):
            require_execution_payload(resolution)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["draft", "published"])
async def test_active_owned_agent_remains_executable(db, mode):
    owner, definition = await _definition_in_mode(db, mode)
    resolution, payload = await resolve_turn_agent_definition(
        db, agent_id=definition.id, owner_id=owner.id
    )
    assert resolution.payload is not None
    assert payload["id"] == definition.id


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["optional_payload", "background"])
async def test_inactive_agent_is_not_silently_downgraded_to_unbound_execution(db, entrypoint):
    owner, definition = await _definition_in_mode(db, "draft")
    definition.is_active = False
    await db.flush()
    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=owner.id
    )
    if entrypoint == "background":
        with pytest.raises(AgentDefinitionExecutionError):
            require_background_execution_payload(
                resolution, logger_=logging.getLogger(__name__), subject="judge"
            )
    else:
        with pytest.raises(HTTPException) as refused:
            execution_payload_or_none(resolution)
        assert refused.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("is_active", [False, True])
async def test_foreign_agent_remains_not_found_without_activation_or_content_disclosure(db, is_active):
    _, definition = await _definition_in_mode(db, "draft")
    caller = await make_user(db, label="foreign-agent-judge")
    # A3: global agents are shared with everyone; a Workspace agent stays hidden from non-members.
    definition.project_id = (await make_project(db)).id
    definition.is_active = is_active
    await db.flush()
    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=caller.id
    )
    assert resolution.payload is None
    with pytest.raises(HTTPException) as request_refusal:
        require_execution_payload(resolution)
    assert request_refusal.value.status_code == 404
    assert request_refusal.value.detail == "Agent not found"
    with pytest.raises(TurnRefusedError) as turn_refusal:
        await resolve_turn_agent_definition(db, agent_id=definition.id, owner_id=caller.id)
    assert turn_refusal.value.refusal.state == TurnRefusalState.AGENT_NOT_FOUND
    assert turn_refusal.value.refusal.detail == "Agent not found"
