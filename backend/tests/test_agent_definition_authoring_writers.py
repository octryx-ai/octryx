"""Package import passes the boundary, which refuses anonymous and failing writes."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_authoring import governed_agent_definition_write
from app.services.agent_definition_writers import AgentDefinitionWriter
from app.services.export_package.upsert import upsert_agent_from_package
from tests.agent_definition_authoring_boundary_support import _audit_rows, _revisions
from tests.agent_definition_revision_fixtures import DEFAULT_STEP_TOOL, admin_user, make_definition

# ---------------------------------------------------------------------------
# Package import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_package_import_passes_the_boundary(db: AsyncSession):
    admin = await admin_user(db)

    agent, warnings = await upsert_agent_from_package(
        db,
        current_user=admin,
        entity={
            "name": "Imported Agent",
            "goal": "Imported goal",
            "agent_type": "diagnosis",
            "thinking_level": "light",
            "steps": [
                {
                    "position": 1,
                    "name": "Imported Step",
                    "step_type": "analysis",
                    "allowed_tools": [DEFAULT_STEP_TOOL],
                }
            ],
        },
        overwrite_existing=False,
        name_override=None  # Global
    )
    await db.commit()
    assert warnings == []

    revisions = await _revisions(db, agent.id)
    assert len(revisions) == 1
    assert revisions[0].status == "draft"
    assert [step["name"] for step in revisions[0].snapshot["steps"]] == ["Imported Step"]

    audit = await _audit_rows(db, agent.id)
    assert len(audit) == 1
    assert audit[0].details["writer"] == AgentDefinitionWriter.PACKAGE_IMPORT.value
    assert audit[0].user_id == admin.id


# ---------------------------------------------------------------------------
# Boundary mechanics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_boundary_refuses_an_anonymous_write(db: AsyncSession):
    with pytest.raises(ValueError, match="actor id"):
        async with governed_agent_definition_write(
            db, writer=AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_id=""
        ):
            pass


@pytest.mark.asyncio
async def test_a_failing_writer_records_nothing(db: AsyncSession):
    """The revision and the audit row exist only for a write that completed."""
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    await db.commit()
    # Captured before the rollback: a rollback expires loaded attributes, and a
    # lazy refresh inside an assertion would be sync IO in async context.
    definition_id = definition.id

    with pytest.raises(RuntimeError):
        async with governed_agent_definition_write(
            db, writer=AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_id=admin.id
        ):
            definition.goal = "Half-written"
            await db.flush()
            raise RuntimeError("writer failed")

    await db.rollback()
    assert await _revisions(db, definition_id) == []
    assert await _audit_rows(db, definition_id) == []
