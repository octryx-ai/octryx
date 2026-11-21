"""Contract: an intake reads through one of its Workspace's connections, has one schedule value, and belongs to one
Workspace.

- a Jira intake on a named connection is confined to that connection's bound projects (save and run); a named
  connection that is gone blocks the run with ``intake_connection_unavailable``, never another connection;
- an unknown ``connection_id``, an intake without a Workspace and one naming no connection are refused (422, coded);
- a schedule preset drives the scheduler; a custom cron is validated.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy import select

from app.models import BuiltInToolConfig, ConnectorNamedConnection, Project, Scheduler, Task, User
from app.services.named_connections.usage import connection_usage
from app.services.secure_work.intake.connections import require_intake_connection
from app.services.secure_work.jira.jira_sync import run_jira_work_item_sync
from app.services.secure_work.jira.jira_sync_config import create_jira_sync_config


async def _setup(db) -> tuple[str, User, str]:
    project = Project(name=f"ws-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    db.add(BuiltInToolConfig(tool_name="jira", project_id=project.id, is_active=True,
                             config={"jira_url": "https://jira.example.test", "jira_allowed_projects": ["CLM", "OPS"]}))
    named = ConnectorNamedConnection(tool_name="jira", project_id=project.id, scope_key=project.id, name="ops-cloud",
                                     config={"jira_url": "https://ops.example.test"}, bound_scopes=["OPS"])
    db.add(named)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await db.commit()
    return project.id, admin, named.id


async def test_a_named_connection_confines_the_intake_and_a_gone_one_blocks_the_run(db):
    project_id, admin, named_id = await _setup(db)
    with pytest.raises(HTTPException) as outside:
        await create_jira_sync_config(db, current_user=admin, payload={
            "name": "Ops", "project_id": project_id, "connection_id": named_id, "filters": {"project_keys": ["CLM"]}})
    assert outside.value.status_code == 409 and outside.value.detail["reason"] == "scope_not_allowed"
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()  # the refusal rolled back
    created = await create_jira_sync_config(db, current_user=admin, payload={
        "name": "Ops", "project_id": project_id, "connection_id": named_id, "filters": {"project_keys": ["OPS"]}})
    assert created["connection_id"] == named_id
    await db.commit()
    usage = await connection_usage(db, "jira", project_id, [named_id])
    assert [entry["name"] for entry in usage[named_id]["work_intakes"]] == ["Ops"]
    await db.execute(sa.delete(ConnectorNamedConnection).where(ConnectorNamedConnection.id == named_id))
    await db.commit()
    with pytest.raises(HTTPException) as gone:
        await run_jira_work_item_sync(db, config_id=created["id"], current_user=admin, payload={}, dry_run=True)
    assert gone.value.detail["code"] == "intake_connection_unavailable"


async def test_unknown_connections_and_workspace_less_intakes_are_refused(db):
    project_id, admin, _ = await _setup(db)
    with pytest.raises(HTTPException) as unknown:
        await require_intake_connection(db, project_id, "jira", "no-such-id")
    assert unknown.value.status_code == 422 and unknown.value.detail["code"] == "intake_connection_not_found"
    assert (await require_intake_connection(db, project_id, "jira", "default"))["scope"] == "workspace"
    with pytest.raises(HTTPException) as no_workspace:
        await create_jira_sync_config(db, current_user=admin, payload={"name": "Global", "filters": {}})
    assert no_workspace.value.detail["code"] == "intake_workspace_required"
    with pytest.raises(HTTPException) as unnamed:
        await create_jira_sync_config(db, current_user=admin, payload={"name": "Unnamed", "project_id": project_id})
    assert unnamed.value.detail["code"] == "intake_connection_not_found"


async def test_a_schedule_preset_drives_the_scheduler(db):
    project_id, admin, _ = await _setup(db)
    created = await create_jira_sync_config(db, current_user=admin, payload={
        "name": "Hourly", "project_id": project_id, "connection_id": "default", "filters": {"project_keys": ["CLM"]},
        "sync_options": {"schedule": {"preset": "hourly"}}})
    assert created["sync_options"]["schedule"] == {"preset": "hourly", "cron": None}
    task = next(row for row in (await db.execute(select(Task))).scalars() if (row.config or {}).get("sync_config_id") == created["id"])
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.task_id == task.id))).scalar_one()
    assert (scheduler.cron_expression, scheduler.is_active) == ("0 * * * *", True)
    with pytest.raises(HTTPException) as bad:
        await create_jira_sync_config(db, current_user=admin, payload={
            "name": "Bad", "project_id": project_id, "connection_id": "default", "sync_options": {"schedule": {"preset": "custom", "cron": "nope"}}})
    assert bad.value.status_code == 422
