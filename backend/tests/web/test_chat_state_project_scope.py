import uuid

import pytest

from app.models import IdentityGroup, Project, ProjectGroup, User, UserGroup, UserProject
from app.web._helpers._chat_state_builder import _list_accessible_chat_projects


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest.mark.asyncio
async def test_chat_project_options_use_direct_project_membership(db):
    suffix = _suffix()
    user = User(
        username=f"direct-chat-project-user-{suffix}",
        email=f"direct-chat-project-user-{suffix}@example.com",
        password_hash="unused",
        is_active=True,
    )
    allowed = Project(name=f"Direct Allowed {suffix}", description="", is_active=True)
    denied = Project(name=f"Direct Denied {suffix}", description="", is_active=True)
    inactive = Project(name=f"Direct Inactive {suffix}", description="", is_active=False)
    db.add_all([user, allowed, denied, inactive])
    await db.flush()
    db.add(UserProject(user_id=user.id, project_id=allowed.id, role="member"))
    db.add(UserProject(user_id=user.id, project_id=inactive.id, role="member"))
    await db.flush()

    projects = await _list_accessible_chat_projects(db, user=user)

    assert [project.id for project in projects] == [allowed.id]


@pytest.mark.asyncio
async def test_chat_project_options_use_group_project_membership(db):
    suffix = _suffix()
    user = User(
        username=f"group-chat-project-user-{suffix}",
        email=f"group-chat-project-user-{suffix}@example.com",
        password_hash="unused",
        is_active=True,
    )
    group = IdentityGroup(name=f"chat-support-{suffix}", is_active=True)
    allowed = Project(name=f"Group Allowed {suffix}", description="", is_active=True)
    denied = Project(name=f"Group Denied {suffix}", description="", is_active=True)
    db.add_all([user, group, allowed, denied])
    await db.flush()
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    db.add(ProjectGroup(project_id=allowed.id, group_id=group.id, role="support"))
    await db.flush()

    projects = await _list_accessible_chat_projects(db, user=user)

    assert [project.id for project in projects] == [allowed.id]
