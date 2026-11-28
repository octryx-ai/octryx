"""An inactive Agent Definition starts no new execution."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.scheduler.execution._step_agent_loader import load_agent_for_step
from app.services.agent_definition_execution import resolve_agent_definition_for_execution
from app.services.agent_definition_execution_outcomes import (
    AgentDefinitionExecutionError,
    require_execution_payload,
)
from app.services.agent_definition_execution_states import (
    AGENT_DEFINITION_EXECUTION_MODE_KEY,
    INACTIVE_ERROR_CODE,
    SOURCE_PUBLISHED_REVISION,
    STATUS_INACTIVE,
)
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from app.services.agent_definition_snapshot import snapshot_header
from app.services.session.agent_selection_sources import AgentSelectionSource
from app.services.system_config.values import set_system_config_value
from tests.agent_definition_revision_fixtures import DEFINITION_GOAL, admin_user, make_definition
from tests.support.turn_agent_selection_support import _workspace
from tests.turn_preparation_support import prepare_chat_turn

INACTIVE_MESSAGE = "This agent is inactive, so it cannot start new turns. Activate it on its agent page to use it again."


def _refusal(definition_id: str) -> dict:
    return {"code": INACTIVE_ERROR_CODE, "message": INACTIVE_MESSAGE, "definition_id": definition_id}


async def _definition(db, mode: str, *, project_id: str | None = None):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, project_id=project_id, steps=1)
    if mode == "published":
        # Published while active: the snapshot records an active definition.
        revision = await create_draft_revision(db, definition=definition, created_by=owner.id)
        await publish_revision(db, revision=revision, published_by=owner.id)
        assert snapshot_header(revision.snapshot)["is_active"] is True
    await set_system_config_value(db, key=AGENT_DEFINITION_EXECUTION_MODE_KEY, value=mode, description="test")
    return owner, definition


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["draft", "published"])
async def test_the_live_switch_refuses_without_building_content_and_reactivation_restores(db, mode):
    owner, definition = await _definition(db, mode)
    definition.is_active = False
    await db.flush()

    resolution = await resolve_agent_definition_for_execution(db, definition_id=definition.id, visible_to_user_id=owner.id)
    assert (resolution.status, resolution.payload, resolution.revision_id) == (STATUS_INACTIVE, None, None)
    with pytest.raises(HTTPException) as refused:
        require_execution_payload(resolution)
    assert refused.value.status_code == 409
    assert refused.value.detail == _refusal(definition.id)

    definition.is_active = True
    await db.flush()
    restored = await resolve_agent_definition_for_execution(db, definition_id=definition.id, visible_to_user_id=owner.id)
    assert restored.resolved and restored.payload["goal"] == DEFINITION_GOAL
    if mode == "published":
        assert restored.source == SOURCE_PUBLISHED_REVISION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        AgentSelectionSource.EXPLICIT,
        AgentSelectionSource.MENTION,
        AgentSelectionSource.SESSION,
        AgentSelectionSource.DEFAULT,
    ],
)
async def test_every_selection_source_refuses_an_inactive_agent_instead_of_falling_back(db, source):
    ws = await _workspace(db, default_agent=True)
    inactive = ws.agents[source.value]
    inactive.is_active = False
    await db.commit()

    with pytest.raises(HTTPException) as refused:
        await prepare_chat_turn(
            db=db,
            user=ws.admin,
            prompt=f"@{inactive.name} continue" if source == AgentSelectionSource.MENTION else "Continue.",
            project_id=ws.project.id,
            session_id=ws.session.id if source == AgentSelectionSource.SESSION else "",
            agent_id=inactive.id if source == AgentSelectionSource.EXPLICIT else "",
        )
    assert refused.value.status_code == 409
    assert refused.value.detail == _refusal(inactive.id)


@pytest.mark.asyncio
async def test_a_background_step_fails_typed_instead_of_running_without_its_agent(db):
    _, definition = await _definition(db, "draft")
    definition.is_active = False
    await db.flush()
    step = SimpleNamespace(connector_params={}, runtime_selector={})
    task = SimpleNamespace(config={"agent_definition_id": definition.id})

    with pytest.raises(AgentDefinitionExecutionError) as refused:
        await load_agent_for_step(step, task, db, logging.getLogger(__name__))
    assert refused.value.code == INACTIVE_ERROR_CODE
    assert refused.value.as_metadata()["status"] == STATUS_INACTIVE
    assert DEFINITION_GOAL not in str(refused.value.as_metadata())


