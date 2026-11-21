"""Shared helpers for the test_work_pull_request_refresh_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Project, User, WorkItem, WorkPullRequest

# --- fixtures ------------------------------------------------------------------------------------------------


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def workspace_item(db, key: str = "OCX-1") -> WorkItem:
    """A Work Item in a Workspace of its own."""
    project = Project(name=f"ws-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    item = WorkItem(project_id=project.id, source_type="jira", source_instance="refresh-test",
                    source_key=f"{key}-{uuid.uuid4().hex[:6]}", title=key, work_state="implementation",
                    sync_state="imported")
    db.add(item)
    await db.commit()
    return item


async def _pr(db, *, work_item_id=None, status="open", provider="bitbucket", number="12", **extra) -> WorkPullRequest:
    """A record bound to its item's Workspace (a new item in a Workspace of its own unless one is given)."""
    item = await db.get(WorkItem, work_item_id) if work_item_id else await workspace_item(db)
    row = WorkPullRequest(
        work_item_id=item.id, scope_key=item.project_id, provider=provider, repository_slug="runtime", pr_id=number,
        pr_url=f"https://git.example.test/projects/OCX/repos/runtime/pull-requests/{number}", status=status,
        created_by=(await _admin(db)).id, **{"provider_instance": "git.example.test", "project_key": "OCX", **extra})
    db.add(row)
    await db.commit()
    return row
