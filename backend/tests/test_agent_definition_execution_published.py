"""In published mode a definition without a published revision is refused on every consumer helper, the published content runs instead of the drifted row, and the resolution metadata and payload provenance agree."""

from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition, AgentStep
from app.services.agent_definition_execution import resolve_agent_definition_for_execution
from app.services.agent_definition_execution_outcomes import (
    AgentDefinitionExecutionError,
    execution_payload_or_none,
    payload_resolution_metadata,
    require_background_execution_payload,
    require_execution_payload,
    resolution_metadata,
)
from app.services.agent_definition_execution_states import (
    EXECUTION_MODE_DRAFT,
    EXECUTION_MODE_PUBLISHED,
    NOT_PUBLISHED_ERROR_CODE,
    PAYLOAD_MODE_KEY,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_REVISION_NUMBER_KEY,
    PAYLOAD_SOURCE_KEY,
    RESOLUTION_METADATA_KEY,
    SOURCE_PUBLISHED_REVISION,
    STATUS_NEEDS_PUBLICATION,
    STATUS_RESOLVED,
)
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from tests.agent_definition_execution_resolution_support import _set_mode
from tests.agent_definition_revision_fixtures import DEFAULT_STEP_TOOL, admin_user, make_definition

PROVENANCE_KEYS = {
    PAYLOAD_MODE_KEY,
    PAYLOAD_SOURCE_KEY,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_REVISION_NUMBER_KEY,
}


# ---------------------------------------------------------------------------
# Published mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_published_mode_refuses_a_definition_with_no_published_revision(
    db: AsyncSession,
):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)

    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )

    assert resolution.status == STATUS_NEEDS_PUBLICATION
    assert resolution.payload is None
    assert resolution.mode == EXECUTION_MODE_PUBLISHED


@pytest.mark.asyncio
async def test_the_refusal_is_explicit_on_every_consumer_helper(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)
    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )

    for helper in (require_execution_payload, execution_payload_or_none):
        with pytest.raises(HTTPException) as raised:
            helper(resolution)
        assert raised.value.status_code == 409
        assert raised.value.detail["code"] == NOT_PUBLISHED_ERROR_CODE
        assert raised.value.detail["definition_id"] == definition.id

    # A background path has no caller to refuse to, so it fails instead: it must
    # never run the configured turn without the configured agent.
    with caplog.at_level(logging.ERROR):
        with pytest.raises(AgentDefinitionExecutionError) as background:
            require_background_execution_payload(
                resolution, logger_=logging.getLogger("test"), subject="unit"
            )
    assert background.value.code == NOT_PUBLISHED_ERROR_CODE
    metadata = background.value.as_metadata()
    assert metadata["status"] == STATUS_NEEDS_PUBLICATION
    assert metadata["definition_id"] == definition.id
    assert NOT_PUBLISHED_ERROR_CODE in caplog.text


@pytest.mark.asyncio
async def test_published_mode_executes_the_published_content_not_the_drifted_row(
    db: AsyncSession,
):
    """The acceptance property of published-mode execution.

    A definition is published, then edited through the live row. Published mode
    must execute the *published* snapshot — otherwise publication decides nothing.
    """
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.flush()

    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=revision, published_by=admin.id)
    published_name = definition.name

    # Drift the live aggregate after publication.
    definition.name = "Drifted Name"
    definition.system_prompt = "Drifted instructions"
    steps = list(
        (
            await db.execute(
                select(AgentStep).where(AgentStep.agent_id == definition.id)
            )
        )
        .scalars()
        .all()
    )
    steps[0].allowed_tools = ["tool_that_does_not_exist"]
    steps[0].instructions = "Drifted step instructions"
    await db.flush()

    await _set_mode(db, EXECUTION_MODE_PUBLISHED)
    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )

    assert resolution.status == STATUS_RESOLVED
    assert resolution.source == SOURCE_PUBLISHED_REVISION
    assert resolution.revision_id == revision.id
    assert resolution.revision_number == 1
    payload = resolution.payload
    assert payload is not None
    assert payload["name"] == published_name
    assert payload["systemPrompt"] == "Be precise."
    assert payload["steps"][0]["allowedTools"] == [DEFAULT_STEP_TOOL]
    assert payload["steps"][0]["instructions"] == "Do Step 1"
    assert "Drifted" not in payload["prompt"]

    # Draft mode is the other explicit half: it executes the drifted row.
    await _set_mode(db, EXECUTION_MODE_DRAFT)
    drafted = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )
    assert drafted.payload is not None
    assert drafted.payload["name"] == "Drifted Name"


@pytest.mark.asyncio
async def test_both_modes_produce_the_same_payload_shape(db: AsyncSession):
    """A consumer cannot tell the source apart by shape, only by provenance."""
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=2)
    await db.flush()
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=revision, published_by=admin.id)

    drafted = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)
    published = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )

    assert drafted.payload is not None and published.payload is not None
    assert set(drafted.payload) == set(published.payload)
    assert set(drafted.payload) >= PROVENANCE_KEYS
    for key in set(drafted.payload) - PROVENANCE_KEYS:
        assert drafted.payload[key] == published.payload[key], key
    assert published.payload[PAYLOAD_SOURCE_KEY] == SOURCE_PUBLISHED_REVISION
    assert published.payload[PAYLOAD_REVISION_NUMBER_KEY] == 1


@pytest.mark.asyncio
async def test_the_seeded_catalog_is_executable_in_published_mode(db: AsyncSession):
    """Bootstrap publishing is what makes published mode usable out of the box."""
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)
    definitions = list((await db.execute(select(AgentDefinition))).scalars().all())
    assert definitions

    for definition in definitions:
        resolution = await resolve_agent_definition_for_execution(
            db, definition_id=definition.id
        )
        assert resolution.status == STATUS_RESOLVED, definition.name
        assert resolution.source == SOURCE_PUBLISHED_REVISION
        assert resolution.payload is not None


# ---------------------------------------------------------------------------
# The canonical metadata entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_resolution_metadata_entry_is_identifiers_only(db: AsyncSession):
    """What sessions, task runs, and traces record must carry no authored content."""
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.flush()
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=revision, published_by=admin.id)
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)

    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )
    entry = resolution_metadata(resolution)[RESOLUTION_METADATA_KEY]

    assert entry == {
        "definition_id": definition.id,
        "mode": EXECUTION_MODE_PUBLISHED,
        "status": STATUS_RESOLVED,
        "source": SOURCE_PUBLISHED_REVISION,
        "revision_id": revision.id,
        "revision_number": 1,
        "checksum": revision.checksum,
    }
    assert "Be precise." not in str(entry)


@pytest.mark.asyncio
async def test_payload_provenance_agrees_with_the_resolution(db: AsyncSession):
    """A consumer holding only the payload records the same source, not a guess."""
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.flush()
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    await publish_revision(db, revision=revision, published_by=admin.id)
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)

    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=definition.id, visible_to_user_id=admin.id
    )
    from_payload = payload_resolution_metadata(resolution.payload)[RESOLUTION_METADATA_KEY]
    from_resolution = resolution_metadata(resolution)[RESOLUTION_METADATA_KEY]

    for key in ("mode", "source", "revision_id", "revision_number"):
        assert from_payload[key] == from_resolution[key], key
    assert payload_resolution_metadata(None) == {}
