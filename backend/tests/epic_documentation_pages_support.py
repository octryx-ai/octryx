"""Shared helpers for the test_epic_documentation_pages_* modules."""

from __future__ import annotations

import subprocess
import uuid

from sqlalchemy import select

from app.models import Project, WorkflowRun, WorkflowRunEvent, WorkItem
from tests.documentation_acceptance_support import documentation_systems
from tests.phased_workflow_fixtures import admin_user


async def _events(db, run, kind: str) -> list[dict]:
    rows = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
                                                            WorkflowRunEvent.kind == kind)
                             .order_by(WorkflowRunEvent.created_at))).scalars().all()
    return [dict(row.detail or {}) for row in rows]


async def _workspace(db, monkeypatch, *, systems: bool = True, auto: bool = True):
    admin = await admin_user(db)
    project = Project(id=str(uuid.uuid4()), name=f"coffee-{uuid.uuid4().hex[:6]}", is_active=True, config={})
    db.add(project)
    await db.flush()
    stub = None
    if systems:
        stub, _source = await documentation_systems(db, project, monkeypatch, requester=admin)
        project.config = {**project.config, "feature_documentation": {
            **project.config["feature_documentation"], **({"auto_publish": True} if auto else {})}}
    tag = uuid.uuid4().hex[:4].upper()
    epic = WorkItem(source_type="platform", source_instance="octryx", source_key=f"CF-{tag}", title="Coffee",
                    issue_type="epic", project_id=project.id, work_state="intake")
    db.add(epic)
    await db.flush()
    stories = []
    for number in (1, 2):
        story = WorkItem(source_type="platform", source_instance="octryx", source_key=f"CF-{tag}-S{number}",
                         title=f"Coffee S{number}", description=f"Goal of story {number}.", epic_key=epic.source_key,
                         project_id=project.id, work_state="intake")
        db.add(story)
        await db.flush()
        stories.append(story)
    await db.commit()
    return admin, project, stub, epic, stories


def _run(admin, project, item, workflow_key, *, after=None, pr=None, context=None) -> WorkflowRun:
    chain = {"epic_chain": {"after_run": after.id}} if after is not None else {}
    return WorkflowRun(project_id=project.id, work_item_id=item.id, workflow_kind="phased", workflow_key=workflow_key,
                       title=item.title, repository="bitbucket:OCX/coffee", branch=f"feature/{item.source_key}",
                       requested_by=admin.id, status="running", current_node_id="docs",
                       pull_request={"id": pr, "url": f"https://bitbucket.example.test/pr/{pr}"} if pr else {},
                       context={**chain, **(context or {})})


def _git(root, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout.strip()
