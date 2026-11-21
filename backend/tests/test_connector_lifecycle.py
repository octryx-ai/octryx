"""Pause/Resume flips only is_active; Remove is refused while used and needs the typed name."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog, BuiltInToolConfig, ConnectorPolicy, Project, User
from app.services.admin.connector.connector_lifecycle import (
    STATE_CONFIRMATION_MISMATCH,
    STATE_CONNECTOR_IN_USE,
    connector_usage,
    guarded_delete_connector,
    set_connector_active,
)


async def _platform_jira(db) -> BuiltInToolConfig:
    entry = BuiltInToolConfig(id=str(uuid.uuid4()), tool_name="jira", project_id=None,
                              config={"jira_url": "https://jira.invalid"}, is_active=True)
    db.add(entry)
    db.add(ConnectorPolicy(connector_name="jira", project_id=None, policy={"disabled_tools": ["jira_delete"]},
                           is_active=True))
    await db.commit()
    return entry


@pytest.mark.asyncio
async def test_pause_keeps_the_policy_and_is_audited(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    entry = await _platform_jira(db)

    paused = await set_connector_active(db, tool_name="jira", is_active=False, actor_user_id=admin.id)

    assert paused == {"tool_name": "jira", "is_active": False}
    await db.refresh(entry)
    assert entry.is_active is False
    policy = (await db.execute(select(ConnectorPolicy).where(ConnectorPolicy.connector_name == "jira"))).scalar_one()
    assert policy.policy["disabled_tools"] == ["jira_delete"], "pausing never rewrites the policy"
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.resource_id == "jira"))).scalars().all()
    assert "admin.connector.paused" in actions


@pytest.mark.asyncio
async def test_remove_is_refused_while_a_workspace_uses_it_and_needs_the_name(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    await _platform_jira(db)
    db.add(BuiltInToolConfig(id=str(uuid.uuid4()), tool_name="jira", project_id=project.id, config={}, is_active=True))
    await db.commit()

    usage = await connector_usage(db, "jira")
    assert usage["workspaces"] == [project.name]

    with pytest.raises(HTTPException) as wrong_name:
        await guarded_delete_connector(db, tool_name="jira", confirm_name="confluence", actor_user_id=admin.id)
    assert wrong_name.value.detail["code"] == STATE_CONFIRMATION_MISMATCH

    with pytest.raises(HTTPException) as in_use:
        await guarded_delete_connector(db, tool_name="jira", confirm_name="Jira", actor_user_id=admin.id)
    assert in_use.value.status_code == 409
    assert in_use.value.detail["code"] == STATE_CONNECTOR_IN_USE

    workspace_row = (
        await db.execute(select(BuiltInToolConfig).where(BuiltInToolConfig.project_id == project.id))
    ).scalar_one()
    await db.delete(workspace_row)
    await db.commit()
    removed = await guarded_delete_connector(db, tool_name="jira", confirm_name="Jira", actor_user_id=admin.id)
    assert removed["status"] == "deleted"
