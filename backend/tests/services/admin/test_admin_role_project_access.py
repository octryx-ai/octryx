"""Effective access diagnostics and project access by direct user and group assignment."""

import pytest

from app.models import Project, UserProject
from app.services.admin.governance.admin_access_service import list_effective_access_diagnostics
from app.services.admin.governance.admin_identity_group_service import create_group
from app.services.admin.governance.admin_role_service import create_role
from app.services.admin.governance.admin_user_service import create_user, update_user
from app.services.admin.project.admin_project_access_service import replace_project_access, replace_project_user_access
from tests.services.admin.admin_role_management_support import _auth_headers_for


@pytest.mark.asyncio
async def test_admin_effective_access_diagnostics_reflect_real_backend_rules(db):
    role = await create_role(
        db,
        payload={
            "name": "knowledge-viewer",
            "description": "Views knowledge",
            "permissions": [{"resource": "knowledge", "action": "read"}],
        },
    )
    group = await create_group(db, payload={"name": "Knowledge Team"})
    user = await create_user(
        db,
        payload={
            "username": "access_user",
            "email": "access-user@example.com",
            "password": "password123",
            "roles": [role["name"]],
        },
    )
    await update_user(db, admin_id="admin", user_id=user["id"], payload={"group_ids": [group["id"]]})
    project = Project(name="access-project", description="Access project", is_active=True)
    db.add(project)
    await db.flush()
    db.add(UserProject(user_id=user["id"], project_id=project.id, role="member"))
    await db.commit()

    diagnostics = await list_effective_access_diagnostics(db)
    row = next(item for item in diagnostics if item["user"]["id"] == user["id"])

    assert row["roles"] == ["knowledge-viewer"]
    assert row["groups"] == ["knowledge team"]
    assert row["permissions"] == [{"resource": "knowledge", "action": "read"}]
    assert row["assigned_projects"] == [
        {
            "id": project.id,
            "name": "access-project",
            "role": "member",
            "project_roles": ["member"],
            "source": "direct",
        }
    ]
    # The sign-in check needs auth:login, which this role does not grant.
    assert row["effective"]["can_use_chat"] is False
    assert row["effective"]["can_open_admin_panel"] is False
    assert "auth:login" in " ".join(row["rules"])


@pytest.mark.asyncio
async def test_admin_effective_access_panel_api(client, auth_headers):
    response = await client.get("/admin/chat/api/panel/effective-access", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert any(item["user"]["username"] == "admin" for item in payload)
    admin_row = next(item for item in payload if item["user"]["username"] == "admin")
    assert admin_row["effective"]["can_open_admin_panel"] is True


@pytest.mark.asyncio
async def test_admin_project_access_service_replaces_direct_user_assignments(db):
    user = await create_user(
        db,
        payload={
            "username": "project_member",
            "email": "project-member@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    project = Project(name="project-access-service", description="Access service", is_active=True)
    db.add(project)
    await db.commit()
    await db.refresh(project)

    payload = await replace_project_user_access(
        db,
        project_id=project.id,
        assignments=[{"user_id": user["id"], "project_role": "owner"}],
        granted_by_user_id="admin",
    )

    assert payload["assignments"][0]["user_id"] == user["id"]
    assert payload["assignments"][0]["project_role"] == "owner"
    assert payload["group_assignments_supported"] is True

    empty_payload = await replace_project_user_access(
        db,
        project_id=project.id,
        assignments=[],
        granted_by_user_id="admin",
    )
    assert empty_payload["assignments"] == []


@pytest.mark.asyncio
async def test_admin_project_access_service_enforces_group_assignments(db):
    group = await create_group(db, payload={"name": "project-access-group"})
    user = await create_user(
        db,
        payload={
            "username": "project_group_member",
            "email": "project-group-member@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    await update_user(db, admin_id="admin", user_id=user["id"], payload={"group_ids": [group["id"]]})
    project = Project(name="project-group-access-service", description="Group access", is_active=True)
    db.add(project)
    await db.commit()
    await db.refresh(project)

    payload = await replace_project_access(
        db,
        project_id=project.id,
        assignments=[],
        group_assignments=[{"group_id": group["id"], "project_role": "viewer"}],
        granted_by_user_id="admin",
    )

    assert payload["group_assignments"][0]["group_id"] == group["id"]
    assert payload["group_assignments"][0]["project_role"] == "viewer"
    diagnostics = await list_effective_access_diagnostics(db)
    row = next(item for item in diagnostics if item["user"]["id"] == user["id"])
    assert row["assigned_projects"] == [
        {
            "id": project.id,
            "name": "project-group-access-service",
            "role": "viewer",
            "project_roles": ["viewer"],
            "source": "group",
            "group": "project-access-group",
        }
    ]
    assert row["effective"]["visible_project_count"] == 1


@pytest.mark.asyncio
async def test_project_list_includes_active_group_access_only(client, auth_headers):
    group = await client.post(
        "/admin/chat/api/panel/identity-groups",
        headers=auth_headers,
        json={"name": "panel-project-group"},
    )
    assert group.status_code == 200, group.text
    user = await client.post(
        "/admin/chat/api/panel/users",
        headers=auth_headers,
        json={
            "username": "panel_group_project_member",
            "email": "panel-group-project-member@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    assert user.status_code == 200, user.text
    updated_user = await client.put(
        f"/admin/chat/api/panel/users/{user.json()['id']}",
        headers=auth_headers,
        json={"group_ids": [group.json()["id"]]},
    )
    assert updated_user.status_code == 200, updated_user.text
    projects = await client.get("/admin/chat/api/panel/projects", headers=auth_headers)
    project_id = projects.json()[0]["id"]
    access = await client.put(
        f"/admin/chat/api/panel/projects/{project_id}/access",
        headers=auth_headers,
        json={
            "assignments": [],
            "group_assignments": [{"group_id": group.json()["id"], "project_role": "member"}],
        },
    )
    assert access.status_code == 200, access.text

    user_headers = await _auth_headers_for(client, "panel_group_project_member")
    visible_projects = await client.get("/api/v1/projects", headers=user_headers)
    assert visible_projects.status_code == 200, visible_projects.text
    assert any(project["id"] == project_id for project in visible_projects.json())

    deactivated = await client.put(
        f"/admin/chat/api/panel/identity-groups/{group.json()['id']}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    visible_after_deactivate = await client.get("/api/v1/projects", headers=user_headers)
    assert visible_after_deactivate.status_code == 200, visible_after_deactivate.text
    assert all(project["id"] != project_id for project in visible_after_deactivate.json())


@pytest.mark.asyncio
async def test_admin_project_access_panel_api_updates_user_assignments(client, auth_headers):
    created = await client.post(
        "/admin/chat/api/panel/users",
        headers=auth_headers,
        json={
            "username": "panel_project_member",
            "email": "panel-project-member@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    assert created.status_code == 200, created.text
    projects = await client.get("/admin/chat/api/panel/projects", headers=auth_headers)
    assert projects.status_code == 200, projects.text
    project_id = projects.json()[0]["id"]

    updated = await client.put(
        f"/admin/chat/api/panel/projects/{project_id}/access",
        headers=auth_headers,
        json={"assignments": [{"user_id": created.json()["id"], "project_role": "member"}]},
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert any(item["user_id"] == created.json()["id"] for item in payload["assignments"])

    loaded = await client.get(f"/admin/chat/api/panel/projects/{project_id}/access", headers=auth_headers)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["rules"]
