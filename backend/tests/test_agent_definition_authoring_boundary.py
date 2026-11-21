"""The governed Agent Definition write boundary, per production writer.

Each test drives one real writer and asserts what the boundary produced: an
immutable revision carrying the validation verdict, one audit row naming the
actor, the writer, the definition, the revision, the Workspace, and the outcome —
and no authored prose anywhere in that audit row.

The panel/legacy-UI response contracts are asserted alongside, because the
boundary must not change them.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin.governance import admin_agent_service
from app.services.agent_definition_authoring import (
    AUDIT_RESOURCE_TYPE,
    OUTCOME_INVALID,
    OUTCOME_RECORDED,
    OUTCOME_UNCHANGED,
)
from app.services.agent_definition_payload import serialize_agent_definition_payload, serialize_agent_step_payload
from app.services.agent_definition_writers import AgentDefinitionWriter
from tests.agent_definition_authoring_boundary_support import SECRET_PROSE, _audit_rows, _revisions
from tests.agent_definition_revision_fixtures import DEFAULT_STEP_TOOL, admin_user, make_definition


async def _first_step_id(db: AsyncSession, definition_id: str) -> str:
    from app.models import AgentStep

    return (
        await db.execute(
            select(AgentStep.id)
            .where(AgentStep.agent_id == definition_id)
            .order_by(AgentStep.position.asc())
            .limit(1)
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Panel CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_panel_create_records_a_validated_draft_revision_and_one_audit_row(
    db: AsyncSession,
):
    admin = await admin_user(db)

    # Global: Workspace-owned agents are not offered in v1 (``test_workspace_agents_d5``).
    created = await admin_agent_service.create_agent(
        db,
        user_id=admin.id,
        payload={
            "name": "Panel Governed Agent",
            "goal": "Prove the boundary",
            "agent_type": "diagnosis",
            "thinking_level": "light",
            "system_prompt": SECRET_PROSE,
        },
        thinking_levels=["light", "deep"],
        serialize_agent_definition=serialize_agent_definition_payload,
    )
    definition_id = created["id"]

    revisions = await _revisions(db, definition_id)
    assert len(revisions) == 1
    revision = revisions[0]
    assert revision.revision_number == 1
    assert revision.status == "draft"
    assert revision.created_by == admin.id
    assert revision.published_at is None
    assert revision.validation == {"ok": True, "issues": []}
    # The revision body *is* the authored content; that is its purpose.
    assert revision.snapshot["definition"]["system_prompt"] == SECRET_PROSE

    audit_rows = await _audit_rows(db, definition_id)
    assert len(audit_rows) == 1
    details = audit_rows[0].details
    assert audit_rows[0].user_id == admin.id
    assert audit_rows[0].resource_type == AUDIT_RESOURCE_TYPE
    assert details["writer"] == AgentDefinitionWriter.PANEL_AGENT_CRUD.value
    assert details["writer_class"] == "production"
    assert details["outcome"] == OUTCOME_RECORDED
    assert details["definition_id"] == definition_id
    assert details["revision_id"] == revision.id
    assert details["revision_number"] == 1
    assert details["revision_status"] == "draft"
    assert details["project_id"] is None
    assert details["checksum"] == revision.checksum
    assert details["validation_issue_codes"] == []


@pytest.mark.asyncio
async def test_the_audit_row_never_carries_authored_prose_or_tool_payloads(
    db: AsyncSession,
):
    """Audit details are identifiers and states only."""
    admin = await admin_user(db)
    created = await admin_agent_service.create_agent(
        db,
        user_id=admin.id,
        payload={
            "name": "Audit Safety Agent",
            "goal": SECRET_PROSE,
            "agent_type": "diagnosis",
            "thinking_level": "light",
            "system_prompt": SECRET_PROSE,
            "output_prompt": SECRET_PROSE,
        },
        thinking_levels=["light"],
        serialize_agent_definition=serialize_agent_definition_payload,
    )
    await admin_agent_service.create_agent_step(
        db,
        user_id=admin.id,
        agent_id=created["id"],
        payload={
            "name": "Step",
            "instructions": SECRET_PROSE,
            "success_criteria": SECRET_PROSE,
            "allowed_tools": [DEFAULT_STEP_TOOL],
        },
        serialize_agent_step=serialize_agent_step_payload,
    )

    audit_rows = await _audit_rows(db, created["id"])
    assert len(audit_rows) == 2
    for row in audit_rows:
        serialized = json.dumps(row.details)
        assert SECRET_PROSE not in serialized
        assert DEFAULT_STEP_TOOL not in serialized
        assert set(row.details) == {
            "writer",
            "writer_class",
            "outcome",
            "definition_id",
            "revision_id",
            "revision_number",
            "revision_status",
            "project_id",
            "checksum",
            "validation_issue_codes",
        }


@pytest.mark.asyncio
async def test_a_step_edit_records_a_new_revision_of_the_whole_aggregate(
    db: AsyncSession,
):
    """A step write is a write of the definition, so it snapshots the aggregate."""
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.commit()

    step_payload = await admin_agent_service.create_agent_step(
        db,
        user_id=admin.id,
        agent_id=definition.id,
        payload={"name": "Added Step", "allowed_tools": [DEFAULT_STEP_TOOL]},
        serialize_agent_step=serialize_agent_step_payload,
    )
    assert step_payload["name"] == "Added Step"

    revisions = await _revisions(db, definition.id)
    assert len(revisions) == 1
    assert [
        step["name"] for step in revisions[0].snapshot["steps"]
    ] == ["Step 1", "Added Step"]


@pytest.mark.asyncio
async def test_a_no_op_update_appends_no_revision_but_is_still_audited(
    db: AsyncSession,
):
    """Only authored *change* produces a revision — but the write is still evidence.

    A governed write whose content is identical appends nothing to the lineage and
    records the explicit ``unchanged`` outcome. Leaving no audit row at all would
    make a governed no-op indistinguishable from an ungoverned write.
    """
    admin = await admin_user(db)
    payload = {
        "name": "Idempotent Agent",
        "goal": "Same every time",
        "agent_type": "diagnosis",
        "thinking_level": "light",
    }
    created = await admin_agent_service.create_agent(
        db,
        user_id=admin.id,
        payload=payload,
        thinking_levels=["light"],
        serialize_agent_definition=serialize_agent_definition_payload,
    )
    first = await _revisions(db, created["id"])
    assert len(first) == 1

    await admin_agent_service.update_agent(
        db,
        user_id=admin.id,
        agent_id=created["id"],
        payload=payload,
        thinking_levels=["light"],
        serialize_agent_definition=serialize_agent_definition_payload,
    )

    second = await _revisions(db, created["id"])
    assert [row.id for row in second] == [first[0].id]

    audit = await _audit_rows(db, created["id"])
    assert [row.details["outcome"] for row in audit] == [
        OUTCOME_RECORDED,
        OUTCOME_UNCHANGED,
    ]
    unchanged = audit[-1].details
    assert unchanged["revision_id"] == first[0].id
    assert unchanged["revision_number"] == 1
    assert unchanged["checksum"] == first[0].checksum


@pytest.mark.asyncio
async def test_invalid_content_is_recorded_as_invalid_and_never_published(
    db: AsyncSession,
):
    """The boundary records the verdict; it does not refuse the live write.

    Panel CRUD has always accepted an unknown tool identifier, and the boundary does not
    change that — refusing here would break the panel before any UI could explain
    why. What changes is that the write now carries an explicit ``invalid``
    verdict, so publication (and therefore published-mode execution) is closed.
    """
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.commit()

    await admin_agent_service.update_agent_step(
        db,
        user_id=admin.id,
        agent_id=definition.id,
        step_id=(await _first_step_id(db, definition.id)),
        payload={"name": "Broken", "allowed_tools": ["tool_that_does_not_exist"]},
        serialize_agent_step=serialize_agent_step_payload,
    )

    revisions = await _revisions(db, definition.id)
    assert len(revisions) == 1
    assert revisions[0].status == "invalid"
    assert revisions[0].published_at is None
    codes = {issue["code"] for issue in revisions[0].validation["issues"]}
    assert codes == {"unknown_tool"}

    audit = (await _audit_rows(db, definition.id))[0]
    assert audit.details["outcome"] == OUTCOME_INVALID
    assert audit.details["validation_issue_codes"] == ["unknown_tool"]
