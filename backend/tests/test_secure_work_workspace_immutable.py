"""Contract: a Work Item and an intake keep the Workspace they were created in.

Every write path that could carry another Workspace refuses the change with a 409 ``workspace_immutable`` before it
writes anything: a Jira intake update of an existing item, an intake draft saved with another ``project_id`` (setup
route and service) and the Jira intake service. No platform or admin path writes an item's ``project_id`` after creation. An intake run's collision guard
(every intake kind, preview and sync) is ``test_intake_workspace_scope.py``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, User, WorkItem, WorkItemSyncConfig
from app.services.secure_work.intake.setup import save_intake
from app.services.secure_work.jira.jira_item_upsert import upsert_jira_work_item


async def _workspaces(db) -> tuple[str, str]:
    own, other = Project(name=f"own-{uuid.uuid4().hex[:6]}", config={}), Project(name=f"oth-{uuid.uuid4().hex[:6]}",
                                                                              config={})
    db.add_all([own, other])
    await db.commit()
    return own.id, other.id


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _item(db, project_id: str, source_type: str) -> WorkItem:
    item = WorkItem(project_id=project_id, source_type=source_type, source_instance="shared-connection",
                    source_id="10001", source_key="OCX-1", title="Original title", work_state="intake",
                    sync_state="imported")
    db.add(item)
    await db.commit()
    return item


def _refused_immutable(refused: pytest.ExceptionInfo) -> bool:
    return refused.value.status_code == 409 and refused.value.detail["code"] == "workspace_immutable"


async def test_a_jira_intake_update_cannot_move_an_item(db):
    own, other = await _workspaces(db)
    item = await _item(db, own, "jira")
    payload = {"project_id": other, "source_type": "jira", "source_instance": "shared-connection",
               "source_key": "OCX-1", "title": "Changed title"}
    with pytest.raises(HTTPException) as refused:
        await upsert_jira_work_item(db, payload, actor_id=(await _admin(db)).id)
    assert _refused_immutable(refused)
    await db.refresh(item)
    assert (item.project_id, item.title) == (own, "Original title")
    assert await upsert_jira_work_item(db, {**payload, "project_id": own}, actor_id=(await _admin(db)).id) == (
        "updated", False)


async def _intake(db, project_id: str) -> WorkItemSyncConfig:
    row = WorkItemSyncConfig(name="intake", project_id=project_id, source_type="jira", source_instance="conn",
                             connection_id="conn", created_by=(await _admin(db)).id)
    db.add(row)
    await db.commit()
    return row


async def test_an_intake_draft_cannot_change_its_workspace(db):
    own, other = await _workspaces(db)
    row = await _intake(db, own)
    with pytest.raises(HTTPException) as refused:
        await save_intake(db, user=await _admin(db), project_id=own, draft={"name": "renamed", "project_id": other},
                          row=row)
    assert _refused_immutable(refused)
    await db.refresh(row)
    assert (row.project_id, row.name) == (own, "intake")


async def test_the_intake_setup_route_refuses_a_workspace_change(client, auth_headers, db):
    own, other = await _workspaces(db)
    row = await _intake(db, own)
    answer = await client.put(f"/api/v1/secure-work/workspaces/{own}/intake/{row.id}", headers=auth_headers,
                              json={"name": "renamed", "project_id": other})
    assert answer.status_code == 409, answer.text
    assert answer.json()["detail"]["code"] == "workspace_immutable"
    await db.refresh(row)
    assert (row.project_id, row.name) == (own, "intake")
