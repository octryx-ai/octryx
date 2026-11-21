"""POST /api/v1/secure-work/work-items creates a platform item over REST, so a client with only an API key (such as
a nightly end-to-end suite copying its bug and story items) needs neither the MCP tool nor a container service call."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import AuditLog, Project, User, UserProject, WorkItem

URL = "/api/v1/secure-work/work-items"


async def _workspace(db, *, member: bool) -> str:
    project = Project(name=f"e2e-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    if member:
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        db.add(UserProject(user_id=admin.id, project_id=project.id, role="admin"))
    await db.commit()
    return project.id


async def test_a_member_creates_a_platform_bug_with_an_audit_row(client, auth_headers, db):
    workspace = await _workspace(db, member=True)
    response = await client.post(URL, headers=auth_headers, json={
        "project_id": workspace, "title": "Grind setting starts at 0.0", "description": "Expected 15.",
        "issue_type": "bug", "labels": ["e2e"]})
    assert response.status_code == 201, response.text
    body = response.json()
    item = await db.get(WorkItem, body["id"])
    assert (item.source_type, item.issue_type, item.work_state, item.project_id) == ("platform", "bug", "intake", workspace)
    assert body["source_key"] == item.source_key and item.labels_json == ["e2e"]
    audit = (await db.execute(select(AuditLog).where(AuditLog.resource_id == item.id))).scalar_one()
    assert audit.action == "secure_work.platform_item_created"


async def test_a_foreign_workspace_and_unknown_fields_are_refused(client, auth_headers, db):
    foreign = await _workspace(db, member=False)
    refused = await client.post(URL, headers=auth_headers, json={"project_id": foreign, "title": "x"})
    assert refused.status_code == 403
    mine = await _workspace(db, member=True)
    unknown = await client.post(URL, headers=auth_headers, json={"project_id": mine, "title": "x", "source_type": "jira"})
    assert unknown.status_code == 422
    assert (await db.execute(select(WorkItem).where(WorkItem.project_id.in_([foreign, mine])))).first() is None
