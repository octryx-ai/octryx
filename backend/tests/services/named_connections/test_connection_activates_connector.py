"""A connection available in a Workspace is enough to use its connector; only an inactive entry switches it off."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, Project
from app.services.named_connections.workspace_routes import active_workspace_entries


@pytest.mark.asyncio
async def test_no_entry_means_usable_and_an_inactive_entry_switches_the_connector_off(db):
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    for row in (await db.execute(select(BuiltInToolConfig).where(
            BuiltInToolConfig.project_id == project.id,
            BuiltInToolConfig.tool_name.in_(["bitbucket", "jira"])))).scalars():
        await db.delete(row)
    await db.flush()
    assert await active_workspace_entries(db, ["bitbucket", "jira"], project.id) == {"bitbucket", "jira"}

    db.add(BuiltInToolConfig(project_id=project.id, tool_name="jira", is_active=False, config={}))
    await db.flush()
    assert await active_workspace_entries(db, ["bitbucket", "jira"], project.id) == {"bitbucket"}
