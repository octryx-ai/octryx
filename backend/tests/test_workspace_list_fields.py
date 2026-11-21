"""Admin › Workspaces list fields: member_count (direct + via group, active, once each) and updated_at."""

from __future__ import annotations

import uuid

import pytest

from app.models import IdentityGroup, Project, ProjectGroup, User, UserGroup, UserProject
from app.services.project.workspace_list_fields import workspace_list_fields
from tests.conftest import ADMIN_PASSWORD


def _user(active: bool = True) -> User:
    return User(id=str(uuid.uuid4()), username=f"wl-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@x.test",
                password_hash="x", is_active=active)


@pytest.mark.asyncio
async def test_member_count_counts_direct_and_group_members_once(db):
    project, empty = Project(name=f"wl-{uuid.uuid4().hex[:6]}", config={}), Project(name=f"wl-{uuid.uuid4().hex[:6]}", config={})
    direct, both, grouped, inactive = _user(), _user(), _user(), _user(active=False)
    group = IdentityGroup(name=f"g-{uuid.uuid4().hex[:6]}")
    db.add_all([project, empty, direct, both, grouped, inactive, group])
    await db.flush()
    db.add_all([UserProject(user_id=direct.id, project_id=project.id), UserProject(user_id=both.id, project_id=project.id),
                UserProject(user_id=inactive.id, project_id=project.id),
                ProjectGroup(project_id=project.id, group_id=group.id),
                UserGroup(user_id=both.id, group_id=group.id), UserGroup(user_id=grouped.id, group_id=group.id)])
    await db.flush()

    fields = await workspace_list_fields(db, [project.id, empty.id])

    assert fields[project.id]["member_count"] == 3  # direct, both (once), grouped; the inactive one not
    assert fields[empty.id]["member_count"] == 0
    assert fields[project.id]["updated_at"].endswith("+00:00") and fields[project.id]["class"] is None


@pytest.mark.asyncio
async def test_the_admin_workspace_list_carries_the_fields(client):
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})).status_code == 303
    rows = (await client.get("/admin/chat/api/panel/projects")).json()
    assert rows and all({"member_count", "updated_at", "class"} <= set(row) for row in rows)
