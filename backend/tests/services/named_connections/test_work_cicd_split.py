"""Contract: CI connections are named ``jenkins`` connections, CI actions go through the agent's CI tools and
the tool approval policy, and Coding → CI runs lists recorded builds read only."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import (
    Project,
    User,
    WorkCicdProviderConfig,
    WorkItem,
)
from app.services.named_connections.descriptors import descriptor_of


async def _world(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project, other = Project(name=f"ci-{uuid.uuid4().hex[:6]}", config={}), Project(name=f"ci-{uuid.uuid4().hex[:6]}", config={})
    db.add_all([project, other])
    await db.flush()
    provider = WorkCicdProviderConfig(name="ci", base_url="https://ci.example.test", created_by=admin.id)
    items = [WorkItem(project_id=pid, source_type="jira", source_instance="ci", source_key=f"CLM-{uuid.uuid4().hex[:12]}",
                      title="t", sync_state="imported") for pid in (project.id, other.id)]
    db.add_all([provider, *items])
    await db.flush()
    return admin, project, provider, items


def test_the_ci_connection_is_a_named_connection_kind():
    descriptor = descriptor_of("jenkins")
    assert descriptor is not None and set(descriptor.secret_fields) == {"jenkins_token"}


async def test_the_provider_and_ci_action_routes_are_gone(db, client, auth_headers):
    _admin, _project, _provider, (item, _other) = await _world(db)
    await db.commit()
    for path in ("/api/v1/secure-work/cicd-providers", "/api/v1/secure-work/cicd-action-policies",
                 f"/api/v1/secure-work/work-items/{item.id}/cicd-actions/request",
                 "/api/v1/secure-work/cicd-action-requests/x/approve"):
        assert (await client.post(path, headers=auth_headers, json={})).status_code in (404, 405), path
