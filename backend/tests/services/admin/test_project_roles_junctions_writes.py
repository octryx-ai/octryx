"""The write path of the project_roles junction tables: assignment rows via replace_project_access, group assignments, access resolution and the empty role list fallback."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import (
    Project,
    ProjectGroupRoleAssignment,
    ProjectUserRoleAssignment,
    UserProject,
)
from app.services.admin.governance.admin_identity_group_service import create_group
from app.services.admin.governance.admin_user_service import create_user, update_user
from app.services.admin.project.admin_project_access_service import (
    get_project_access,
    replace_project_access,
)
from app.services.project.service import get_project_access_details

# --------------------------------------------------------------------------- #
# Write path: assignment add / remove
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_replace_project_access_writes_child_rows(db) -> None:
    user = await create_user(
        db,
        payload={
            "username": "junction_user",
            "email": "junction-user@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    project = Project(name="junction-project", description="junction", is_active=True)
    db.add(project)
    await db.commit()
    await db.refresh(project)

    # Add: two project roles for the user.
    await replace_project_access(
        db,
        project_id=project.id,
        assignments=[{"user_id": user["id"], "project_roles": ["owner", "viewer"]}],
        granted_by_user_id="admin",
    )
    rows = (
        await db.execute(
            select(ProjectUserRoleAssignment.role_name)
            .where(
                ProjectUserRoleAssignment.project_id == project.id,
                ProjectUserRoleAssignment.user_id == user["id"],
            )
            .order_by(ProjectUserRoleAssignment.role_name.asc())
        )
    ).scalars().all()
    assert rows == ["owner", "viewer"]

    # The UserProject grant still carries the primary role.
    grant = (
        await db.execute(
            select(UserProject).where(
                UserProject.project_id == project.id, UserProject.user_id == user["id"]
            )
        )
    ).scalar_one()
    assert grant.role == "owner"

    # Serializer reflects the child rows.
    access = await get_project_access(db, project_id=project.id)
    assert access["assignments"][0]["project_roles"] == ["owner", "viewer"]

    # Remove: replacing with an empty user list drops all child rows.
    await replace_project_access(
        db,
        project_id=project.id,
        assignments=[],
        granted_by_user_id="admin",
    )
    remaining = (
        await db.execute(
            select(ProjectUserRoleAssignment).where(
                ProjectUserRoleAssignment.project_id == project.id
            )
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_group_assignment_writes_child_rows_and_resolves(db) -> None:
    group = await create_group(db, payload={"name": "junction-group"})
    user = await create_user(
        db,
        payload={
            "username": "junction_group_member",
            "email": "junction-group-member@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    await update_user(db, admin_id="admin", user_id=user["id"], payload={"group_ids": [group["id"]]})
    project = Project(name="junction-group-project", description="grp", is_active=True)
    db.add(project)
    await db.commit()
    await db.refresh(project)

    await replace_project_access(
        db,
        project_id=project.id,
        assignments=[],
        group_assignments=[{"group_id": group["id"], "project_roles": ["viewer", "member"]}],
        granted_by_user_id="admin",
    )

    child = (
        await db.execute(
            select(ProjectGroupRoleAssignment.role_name)
            .where(ProjectGroupRoleAssignment.project_id == project.id)
            .order_by(ProjectGroupRoleAssignment.role_name.asc())
        )
    ).scalars().all()
    assert child == ["member", "viewer"]

    # Access resolution merges the group-derived roles for the member.
    access = await get_project_access_details(user["id"], db)
    row = next(item for item in access if item["id"] == project.id)
    assert sorted(row["project_roles"]) == ["member", "viewer"]
    assert row["source"] == "group"


# --------------------------------------------------------------------------- #
# Empty-list handling: no child rows falls back to the grant's primary role
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_empty_role_list_falls_back_to_primary_role(db) -> None:
    user = await create_user(
        db,
        payload={
            "username": "junction_fallback_user",
            "email": "junction-fallback@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    project = Project(name="junction-fallback-project", description="fb", is_active=True)
    db.add(project)
    await db.flush()
    # A grant with NO child role rows (mirrors bootstrap / invitation writes that
    # only set role=).
    db.add(UserProject(user_id=user["id"], project_id=project.id, role="member"))
    await db.commit()

    access = await get_project_access_details(user["id"], db)
    row = next(item for item in access if item["id"] == project.id)
    assert row["project_roles"] == ["member"]
    assert row["role"] == "member"

    serialized = await get_project_access(db, project_id=project.id)
    assert serialized["assignments"][0]["project_roles"] == ["member"]
