"""Explicit runtime resolution of an Agent Definition."""

from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserProject
from app.services.agent_definition_execution import (
    get_agent_definition_execution_mode,
    resolve_agent_definition_for_execution,
)
from app.services.agent_definition_execution_outcomes import (
    AgentDefinitionExecutionError,
    execution_payload_or_none,
    require_background_execution_payload,
    require_execution_payload,
)
from app.services.agent_definition_execution_states import (
    AGENT_DEFINITION_EXECUTION_MODE_KEY,
    EXECUTION_MODE_DRAFT,
    EXECUTION_MODE_UNKNOWN,
    NOT_CONFIGURED_ERROR_CODE,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_SOURCE_KEY,
    SOURCE_LIVE_DRAFT_ROW,
    STATUS_NEEDS_CONFIGURATION,
    STATUS_NOT_FOUND,
    STATUS_RESOLVED,
    AgentDefinitionExecutionModeError,
)
from app.services.agent_definition_payload import serialize_agent_definition_payload
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_project, make_user
from tests.services.agents.agent_definition_execution_resolution_support import _set_mode


@pytest.mark.asyncio
async def test_the_default_mode_is_the_alpha_authoring_draft_contract(db: AsyncSession):
    assert await get_agent_definition_execution_mode(db) == EXECUTION_MODE_DRAFT


@pytest.mark.asyncio
async def test_a_blank_mode_value_is_still_the_documented_default(db: AsyncSession):
    await _set_mode(db, "   ")
    assert await get_agent_definition_execution_mode(db) == EXECUTION_MODE_DRAFT


@pytest.mark.asyncio
async def test_an_explicitly_unknown_mode_is_refused_not_defaulted(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
):
    await _set_mode(db, "publsihed")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(AgentDefinitionExecutionModeError):
            await get_agent_definition_execution_mode(db)
    assert AGENT_DEFINITION_EXECUTION_MODE_KEY in caplog.text
    # The configured value is admin-authored free text and is never echoed.
    assert "publsihed" not in caplog.text


@pytest.mark.asyncio
async def test_an_unknown_mode_resolves_to_needs_configuration(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await _set_mode(db, "on")

    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )

    assert resolution.status == STATUS_NEEDS_CONFIGURATION
    assert resolution.mode == EXECUTION_MODE_UNKNOWN
    assert resolution.payload is None

    for helper in (require_execution_payload, execution_payload_or_none):
        with pytest.raises(HTTPException) as raised:
            helper(resolution)
        assert raised.value.status_code == 409
        assert raised.value.detail["code"] == NOT_CONFIGURED_ERROR_CODE

    with pytest.raises(AgentDefinitionExecutionError) as background:
        require_background_execution_payload(
            resolution, logger_=logging.getLogger("test"), subject="unit"
        )
    assert background.value.code == NOT_CONFIGURED_ERROR_CODE
    assert background.value.as_metadata()["status"] == STATUS_NEEDS_CONFIGURATION


@pytest.mark.asyncio
async def test_draft_mode_resolves_the_live_row_and_says_so(db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=2)
    await db.flush()

    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )

    assert resolution.status == STATUS_RESOLVED
    assert resolution.mode == EXECUTION_MODE_DRAFT
    assert resolution.source == SOURCE_LIVE_DRAFT_ROW
    assert resolution.revision_id is None

    payload = resolution.payload
    assert payload is not None
    live = serialize_agent_definition_payload(definition)
    for key, value in live.items():
        assert payload[key] == value, key
    assert payload["prompt"].startswith(f"Selected agent: {definition.name}")
    assert payload[PAYLOAD_SOURCE_KEY] == SOURCE_LIVE_DRAFT_ROW
    assert payload[PAYLOAD_REVISION_ID_KEY] is None


@pytest.mark.asyncio
async def test_resolution_is_scoped_to_what_the_user_may_see(db: AsyncSession):
    admin = await admin_user(db)
    member = await make_user(db, label="member")
    outsider = await make_user(db, label="outsider")
    project = await make_project(db)
    db.add(UserProject(user_id=member.id, project_id=project.id, role="member"))
    definition = await make_definition(db, owner=admin, steps=1, project_id=project.id)
    await db.flush()

    shared = await resolve_agent_definition_for_execution(db, definition_id=definition.id, visible_to_user_id=member.id)
    assert shared.status == STATUS_RESOLVED

    hidden = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=outsider.id
    )
    assert hidden.status == STATUS_NOT_FOUND
    assert hidden.payload is None

    unscoped = await resolve_agent_definition_for_execution(db, definition_id=definition.id)
    assert unscoped.status == STATUS_RESOLVED
