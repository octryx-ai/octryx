"""Contract: work_pull_requests is the one PR source."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Project, User, WorkItem
from app.services.secure_work.pull_requests.pull_requests import sync_pull_request
from app.services.secure_work.pull_requests.record_identity import pull_request_identity


async def test_a_recorded_pr_reaches_coding(client, auth_headers, db):
    project = Project(name=f"pr-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    item = WorkItem(project_id=project.id, source_type="jira", source_instance="pr-source", source_key="CLM-198",
                    title="Rename legacy status codes", work_state="review", sync_state="imported")
    db.add(item)
    await db.commit()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await sync_pull_request(db, current_user=admin, workspace_id=project.id, payload={
        "work_item_id": item.id, "status": "open",
        "identity": pull_request_identity("bitbucket", "https://scm.example.test/claims-api/pull-requests/482",
                                          "CLM/claims-api", "482"), "pr_url": "https://scm.example.test/claims-api/pull-requests/482",
        "title": "Rename legacy status codes"})
    await db.commit()
    await db.refresh(item)
    assert "pull_requests" not in (item.source_fields_json or {})
    candidates = (await client.get("/api/v1/secure-work/coding-sessions", headers=auth_headers)).json()["items"]
    entry = next(entry for entry in candidates if entry["work_item"]["id"] == item.id)
    assert [pr["pr_url"] for pr in entry["pull_requests"]] == ["https://scm.example.test/claims-api/pull-requests/482"]
