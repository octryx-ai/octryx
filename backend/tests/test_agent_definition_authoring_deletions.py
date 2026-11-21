"""Governed deletions of agent definitions and agent groups and the detach of group members."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition, AgentGroup
from app.services.admin.governance import admin_agent_service
from app.services.agent_definition_authoring import AUDIT_RESOURCE_TYPE, OUTCOME_DELETED, OUTCOME_RECORDED
from app.services.agent_definition_writers import AgentDefinitionWriter
from app.services.agent_group import delete_agent_group
from tests.agent_definition_authoring_boundary_support import _audit_rows, _governed_audit_count, _revisions
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_group


@pytest.mark.asyncio
async def test_deleting_a_definition_records_the_deletion_without_a_revision(
    db: AsyncSession,
):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.commit()
    definition_id = definition.id

    result = await admin_agent_service.delete_agent(
        db, user_id=admin.id, agent_id=definition_id
    )
    assert result == {"status": "deleted"}

    assert await _revisions(db, definition_id) == []
    audit = await _audit_rows(db, definition_id)
    assert len(audit) == 1
    assert audit[0].details["outcome"] == OUTCOME_DELETED
    assert audit[0].details["revision_id"] is None


# ---------------------------------------------------------------------------
# Agent group delete: an aggregate write reached through a relationship
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_an_agent_group_governs_the_detach_of_its_members(
    db: AsyncSession,
):
    """Detaching a member definition is an authored-content write, so it is governed.

    ``group_id`` is part of the revision snapshot, so clearing it changes the
    definition's checksum. ``delete_agent_group`` reached the definitions through
    ``AgentGroup.agents`` and cleared it with no revision, no validation verdict, and
    no audit row — the aggregate drifted from its published content outside the one
    boundary that is supposed to see every such write.
    """
    admin = await admin_user(db)
    group = await make_group(db, owner=admin)
    definition = await make_definition(db, owner=admin, steps=1)
    definition.group_id = group.id
    await db.commit()
    definition_id = definition.id
    assert await _revisions(db, definition_id) == []

    assert await delete_agent_group(db, user_id=admin.id, group_id=group.id) == {
        "status": "deleted"
    }
    assert await db.get(AgentGroup, group.id) is None

    detached = await db.get(AgentDefinition, definition_id)
    assert detached is not None
    assert detached.group_id is None

    revisions = await _revisions(db, definition_id)
    assert len(revisions) == 1
    assert revisions[0].revision_number == 1
    # The revision records the content that now executes, not the content it had.
    assert revisions[0].snapshot["definition"]["group_id"] is None
    assert revisions[0].validation["ok"] is True

    audit = await _audit_rows(db, definition_id)
    assert len(audit) == 1
    assert audit[0].user_id == admin.id
    assert audit[0].resource_type == AUDIT_RESOURCE_TYPE
    details = audit[0].details
    assert details["writer"] == AgentDefinitionWriter.PANEL_AGENT_GROUP_DELETE.value
    assert details["writer_class"] == "production"
    assert details["outcome"] == OUTCOME_RECORDED
    assert details["revision_id"] == revisions[0].id
    assert details["checksum"] == revisions[0].checksum


@pytest.mark.asyncio
async def test_deleting_an_unknown_agent_group_records_nothing(db: AsyncSession):
    """The 404 is raised before the scope opens, so no evidence is invented."""
    admin = await admin_user(db)
    before = await _governed_audit_count(db)

    with pytest.raises(HTTPException) as raised:
        await delete_agent_group(db, user_id=admin.id, group_id=str(uuid.uuid4()))

    assert raised.value.status_code == 404
    assert await _governed_audit_count(db) == before
