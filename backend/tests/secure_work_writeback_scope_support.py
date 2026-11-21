"""Shared helpers for the test_secure_work_writeback_scope_* modules."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Project, User, WorkItem, WorkItemWorkflowDefinition
from app.services.secure_work import transition_preview, workflow_mapping
from app.services.secure_work.jira import jira_state_sync
from app.time_utils import utc_now

MAPPING = {"development": {"source_transition": "Start Progress", "sync_back": True}}


@pytest.fixture
async def world(db):
    """Workspaces A and B, the admin, and no other active definition (the test's savepoint undoes it)."""
    for row in (await db.execute(select(WorkItemWorkflowDefinition))).scalars():
        row.is_active = False
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    suffix = uuid.uuid4().hex[:8]
    a, b = Project(name=f"Scope A {suffix}"), Project(name=f"Scope B {suffix}")
    db.add_all([a, b])
    await db.flush()
    return SimpleNamespace(db=db, admin=admin, a=a.id, b=b.id)


@pytest.fixture
def connectors(monkeypatch):
    """Count every connector read and write a transition could make; none of them leaves the process."""
    calls: list[str] = []

    async def _offered(_db, *, item, preview):
        calls.append("check_offered_transition")

    async def _connection(_db, _item, _source_type):
        calls.append("work_item_connection_config")
        return None, "patched"

    async def _sync(_db, *, item, workflow, preview):
        calls.append("execute_tracker_state_sync")
        return {"status": "executed", "executed": True}

    monkeypatch.setattr(transition_preview, "check_offered_transition", _offered)
    monkeypatch.setattr(jira_state_sync, "work_item_connection_config", _connection)
    monkeypatch.setattr(workflow_mapping, "execute_tracker_state_sync", _sync)
    return calls


async def _definition(world, project_id: str | None, *, active: bool = True, default: bool = False,
                      updated_at=None) -> WorkItemWorkflowDefinition:
    row = WorkItemWorkflowDefinition(
        name=f"wb-{uuid.uuid4().hex[:6]}", project_id=project_id, states_json=[], mappings_json=MAPPING,
        sync_policy_json={"sync_mode": "execute"}, is_default=default, is_active=active,
        created_by=world.admin.id, updated_by=world.admin.id, updated_at=updated_at or utc_now(),
    )
    world.db.add(row)
    await world.db.flush()
    return row


async def _item(world, project_id: str | None, *, work_state: str = "intake") -> WorkItem:
    item = WorkItem(source_type="jira", source_instance="scope-test", source_key=f"BRD-{uuid.uuid4().hex[:6]}",
                    title="Scoped write-back", project_id=project_id, work_state=work_state, sync_state="imported")
    world.db.add(item)
    await world.db.flush()
    return item
