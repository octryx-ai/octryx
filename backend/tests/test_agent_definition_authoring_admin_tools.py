"""The model-facing admin tools pass the boundary and malformed tool steps are rejected before it opens."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition
from app.services.agent_definition_writers import AgentDefinitionWriter
from tests.agent_definition_authoring_boundary_support import (
    SECRET_PROSE,
    _audit_rows,
    _governed_audit_count,
    _revisions,
)
from tests.agent_definition_revision_fixtures import DEFAULT_STEP_TOOL, admin_user, make_project

# ---------------------------------------------------------------------------
# Model-facing admin tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_model_facing_admin_tools_pass_the_boundary(db: AsyncSession):
    """``admin_create_agent`` / ``admin_update_agent`` are governed too.

    These are the two paths where the *model* can change an agent's instructions
    and tool allow-list, so an ungoverned write here would be the widest hole in
    the publication contract.
    """
    from pathlib import Path

    from app.tools.context import ToolContext
    from app.tools.registry import TOOL_REGISTRY

    admin = await admin_user(db)
    project = await make_project(db)
    context = ToolContext(
        user_id=admin.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="session",
        project_config={},
        db=db,
        workspace_root=str(Path.cwd()),
    )

    created = await TOOL_REGISTRY["admin_create_agent"].execute(
        {
            "name": "Tool Created Agent",
            "goal": "Created by a tool",
            "agent_type": "diagnosis",
            "steps": [
                {
                    "name": "Look",
                    "step_type": "analysis",
                    "allowed_tools": [DEFAULT_STEP_TOOL],
                }
            ],
        },
        context,
    )
    assert created["status"] == "created"
    definition_id = created["agent"]["id"]

    create_audit = await _audit_rows(db, definition_id)
    assert len(create_audit) == 1
    assert create_audit[0].details["writer"] == AgentDefinitionWriter.ADMIN_TOOL_CREATE.value
    assert len(await _revisions(db, definition_id)) == 1

    updated = await TOOL_REGISTRY["admin_update_agent"].execute(
        {"agent_id": definition_id, "system_prompt": SECRET_PROSE},
        context,
    )
    assert updated["status"] == "updated"

    revisions = await _revisions(db, definition_id)
    assert len(revisions) == 2
    assert revisions[1].snapshot["definition"]["system_prompt"] == SECRET_PROSE
    update_audit = await _audit_rows(db, definition_id)
    assert len(update_audit) == 2
    assert update_audit[1].details["writer"] == AgentDefinitionWriter.ADMIN_TOOL_UPDATE.value
    assert SECRET_PROSE not in json.dumps(update_audit[1].details)


@pytest.mark.asyncio
async def test_a_malformed_tool_step_is_rejected_before_the_boundary_opens(
    db: AsyncSession,
):
    """A returned error must not leave a revision and an audit row behind.

    ``return`` from inside the governed scope exits the context manager *normally*, so
    the boundary finalized: the model was told ``steps[1] must be an object`` while a
    draft revision and an audit row recorded a governed write of the half-built
    definition. The argument check therefore runs ahead of the scope.
    """
    from pathlib import Path

    from app.tools.context import ToolContext
    from app.tools.registry import TOOL_REGISTRY

    admin = await admin_user(db)
    project = await make_project(db)
    await db.commit()
    context = ToolContext(
        user_id=admin.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="session",
        project_config={},
        db=db,
        workspace_root=str(Path.cwd()),
    )
    before = await _governed_audit_count(db)

    result = await TOOL_REGISTRY["admin_create_agent"].execute(
        {
            "name": "Rejected Tool Agent",
            "agent_type": "diagnosis",
            "steps": [
                {"name": "Look", "step_type": "analysis", "allowed_tools": [DEFAULT_STEP_TOOL]},
                "not-an-object",
            ],
        },
        context,
    )

    # The contract is unchanged, including the index in the message.
    assert result == {"error": "steps[1] must be an object"}
    # Nothing was authored, so nothing was recorded — and nothing was half-written.
    assert await _governed_audit_count(db) == before
    assert (
        await db.execute(
            select(AgentDefinition).where(AgentDefinition.name == "Rejected Tool Agent")
        )
    ).scalar_one_or_none() is None
