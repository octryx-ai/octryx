"""An Epic's progress over the API: every story in the lane its own events give it, sub-tasks under their story, and
an Epic outside the reader's Workspaces not found."""

from __future__ import annotations

import uuid

from app.models import Project, UserProject, WorkflowRun, WorkItem, WorkPullRequest
from tests.devices.device_support import user_named
from tests.policy_engine_support import bearer

PROGRESS = "/api/v1/secure-work/work-items/{}/progress"


def _item(project_id: str, key: str, **columns) -> WorkItem:
    return WorkItem(project_id=project_id, source_type="manual", source_instance="pv1", source_key=key, title=key,
                    sync_state="imported", **{"work_state": "intake", **columns})


async def _epic_with_stories(db, user_id: str) -> tuple[WorkItem, dict[str, WorkItem]]:
    project = Project(name=f"pv1-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    epic = _item(project.id, "EP-1", issue_type="Epic")
    stories = {key: _item(project.id, key, issue_type="Story", epic_key="EP-1", **columns) for key, columns in {
        "S-1": {"work_state": "done", "source_status": "Done"},
        "S-2": {"work_state": "development"},
        "S-3": {},
        "S-4": {},
        "S-5": {"work_state": "rejected"},
        "S-6": {},
    }.items()}
    tasks = [_item(project.id, "T-1", issue_type="Sub-task", parent_key="S-2", work_state="done"),
             _item(project.id, "T-2", issue_type="Sub-task", parent_key="S-2")]
    db.add_all([epic, *stories.values(), *tasks, _item(project.id, "OTHER", epic_key="EP-2")])
    await db.flush()
    db.add(WorkflowRun(project_id=project.id, work_item_id=stories["S-3"].id, workflow_kind="phased",
                       workflow_key="feature-delivery", requested_by=user_id, status="running"))
    for key, status, build in (("S-4", "open", "failed"), ("S-6", "merged", "successful")):
        db.add(WorkPullRequest(work_item_id=stories[key].id, scope_key=project.id, created_by=user_id,
                               repository_slug="acme/app", pr_id=key, pr_url=f"https://scm.test/acme/app/pull/{key}",
                               status=status, build_status=build))
    await db.commit()
    return epic, stories


async def test_each_story_is_in_the_lane_of_its_own_events(client, auth_headers, db, auth_user):
    epic, _stories = await _epic_with_stories(db, auth_user.id)

    response = await client.get(PROGRESS.format(epic.id), headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    lanes = {row["key"]: (row["lane"], row["reason"], row["checks"], row["needs_you"]) for row in body["stories"]}
    assert lanes == {
        "S-1": ("done", "done", None, False),
        "S-2": ("in_progress", "development", None, False),
        "S-3": ("in_progress", "running", None, False),
        "S-4": ("in_review", "pull request open", "failed", True),
        "S-5": ("done", "won't do", None, False),
        "S-6": ("done", "merged", None, False),
    }
    assert body["summary"] == {"done": 3, "in_review": 1, "in_progress": 2, "open": 0, "total": 6, "needs_you": 1}
    s2 = next(row for row in body["stories"] if row["key"] == "S-2")
    assert [task["key"] for task in s2["tasks"]] == ["T-1", "T-2"] and s2["tasks_done"] == 1
    s4 = next(row for row in body["stories"] if row["key"] == "S-4")
    assert s4["pull_request"] == {"url": "https://scm.test/acme/app/pull/S-4", "status": "open"}
    assert body["epic"]["key"] == "EP-1"


async def test_an_epic_in_a_workspace_the_reader_is_not_a_member_of_is_not_found(client, db, auth_user):
    epic, _stories = await _epic_with_stories(db, auth_user.id)
    reader = await user_named(db, f"pv1-reader-{uuid.uuid4().hex[:6]}")
    own = Project(name=f"pv1-own-{uuid.uuid4().hex[:6]}", config={})
    db.add(own)
    await db.flush()
    db.add(UserProject(user_id=reader.id, project_id=own.id, role="member"))
    await db.commit()

    response = await client.get(PROGRESS.format(epic.id), headers=bearer(reader.id))

    assert response.status_code == 404, response.text
    assert "EP-1" not in response.text and "S-1" not in response.text
