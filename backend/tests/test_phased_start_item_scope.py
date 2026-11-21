"""Contract: a chat's phased start uses a Work Item of the chat's Workspace only.

An item the card names by id and the row the Jira sync stored under the new issue's key are read through
``phased_start_jira.chat_workspace_item``: an item of another Workspace (even one the person may open) answers
exactly like a missing one; the chat Workspace's own item is used.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, UserProject, WorkItem
from app.services.workflow_routing.phased_start_jira import jira_work_item
from app.services.workflow_routing.phased_start_run import _new_item
from tests.jira_task_list_support import _operator


async def _setup(db):
    own, other = Project(name=f"own-{uuid.uuid4().hex[:6]}", config={}), Project(name=f"oth-{uuid.uuid4().hex[:6]}",
                                                                              config={})
    db.add_all([own, other])
    await db.flush()
    member = await _operator(db)
    db.add_all([UserProject(user_id=member.id, project_id=own.id, role="admin"),
                UserProject(user_id=member.id, project_id=other.id, role="admin")])  # may open both
    await db.commit()
    return member, own.id, other.id


async def _synced(db, project_id: str, key: str) -> WorkItem:
    item = WorkItem(project_id=project_id, source_type="jira", source_instance="default", source_key=key,
                    title=f"synced {key}", work_state="intake", sync_state="imported")
    db.add(item)
    await db.commit()
    return item


def _start(project_id: str, item_id: str) -> dict:
    return {"project_id": project_id, "summary": "Start", "work_item": {
        "mode": "existing", "id": item_id, "key": None, "title": "Card title", "description": "", "type": "Task"}}


async def _items_of(db, project_id: str) -> list[str]:
    rows = (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all()
    return sorted(row.title for row in rows)


async def test_a_card_item_of_another_workspace_is_used_like_a_missing_one(db):
    member, own, other = await _setup(db)
    foreign = await _synced(db, other, "OTH-1")
    mine = await _synced(db, own, "OWN-1")

    assert (await _new_item(db, member, _start(own, mine.id), None)).id == mine.id
    from_foreign = await _new_item(db, member, _start(own, foreign.id), None)
    from_missing = await _new_item(db, member, _start(own, str(uuid.uuid4())), None)
    for created in (from_foreign, from_missing):  # both: a new item of the chat's Workspace, never the foreign one
        assert created.id != foreign.id and created.project_id == own and created.title == "Card title"
    assert await _items_of(db, other) == ["synced OTH-1"]


@pytest.mark.parametrize("synced_in", ["own", "other"])
async def test_the_synced_row_of_a_new_issue_must_be_the_chat_workspaces(db, synced_in):
    member, own, other = await _setup(db)
    synced = await _synced(db, own if synced_in == "own" else other, "CHEF-12")
    jira = {"key": "CHEF-12", "id": None, "project_key": "CHEF", "issue_type": "Epic"}
    item = {"title": "Pantry", "description": ""}
    if synced_in == "own":
        assert (await jira_work_item(db, user=member, project_id=own, item=item, jira=jira)).id == synced.id
        return
    with pytest.raises(HTTPException) as refused:
        await jira_work_item(db, user=member, project_id=own, item=item, jira=jira)
    assert (refused.value.status_code, refused.value.detail) == (404, "Work Item not found")
    await db.refresh(synced)
    assert (synced.project_id, synced.title) == (other, "synced CHEF-12")
