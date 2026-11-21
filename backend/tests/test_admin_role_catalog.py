"""The role catalog: custom role creation, assignment, permissions, core role protection and the role panel APIs."""

import pytest
from sqlalchemy import select

from app.models import Role
from app.services.admin.governance.admin_role_service import (
    create_role,
    delete_role,
    list_permission_catalog,
    list_roles,
    update_role,
)
from app.services.admin.governance.admin_user_service import create_user, update_user


@pytest.mark.asyncio
async def test_admin_role_catalog_create_assign_and_delete_guard(db):
    created = await create_role(
        db,
        payload={"name": "release-manager", "description": "Can coordinate releases"},
    )
    assert created["name"] == "release-manager"
    assert created["is_core"] is False

    user = await create_user(
        db,
        payload={
            "username": "release_user",
            "email": "release-user@example.com",
            "password": "password123",
            "roles": ["release-manager"],
        },
    )
    assert user["roles"] == ["release-manager"]

    roles = await list_roles(db)
    custom = next(role for role in roles if role["name"] == "release-manager")
    assert custom["user_count"] == 1
    assert custom["assigned_users"] == [
        {"id": user["id"], "username": "release_user", "email": "release-user@example.com"}
    ]

    with pytest.raises(Exception) as assigned_error:
        await delete_role(db, role_id=custom["id"])
    assert "assigned" in str(assigned_error.value).lower()

    await update_user(db, admin_id="admin", user_id=user["id"], payload={"roles": ["viewer"]})
    deleted = await delete_role(db, role_id=custom["id"])
    assert deleted == {"status": "deleted"}


@pytest.mark.asyncio
async def test_admin_role_catalog_protects_core_roles_and_immutable_names(db):
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    with pytest.raises(Exception) as core_error:
        await delete_role(db, role_id=admin_role.id)
    assert "core" in str(core_error.value).lower()

    updated = await update_role(
        db,
        role_id=admin_role.id,
        payload={"description": "Global platform administrator"},
    )
    assert updated["description"] == "Global platform administrator"

    with pytest.raises(Exception) as rename_error:
        await update_role(db, role_id=admin_role.id, payload={"name": "super-admin"})
    assert "immutable" in str(rename_error.value).lower()


@pytest.mark.asyncio
async def test_admin_role_catalog_manages_custom_role_permissions(db):
    created = await create_role(
        db,
        payload={
            "name": "knowledge-curator",
            "description": "Maintains knowledge entries",
            "permissions": [
                {"resource": "knowledge", "action": "read"},
                {"resource": "knowledge", "action": "write"},
            ],
        },
    )
    assert created["permissions"] == [
        {"resource": "knowledge", "action": "read"},
        {"resource": "knowledge", "action": "write"},
    ]

    updated = await update_role(
        db,
        role_id=created["id"],
        payload={"permissions": [{"resource": "audit", "action": "read"}]},
    )
    assert updated["permissions"] == [{"resource": "audit", "action": "read"}]

    with pytest.raises(Exception) as invalid_error:
        await update_role(
            db,
            role_id=created["id"],
            payload={"permissions": [{"resource": "unknown", "action": "write"}]},
        )
    assert "unsupported permission" in str(invalid_error.value).lower()

    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    with pytest.raises(Exception) as core_error:
        await update_role(
            db,
            role_id=admin_role.id,
            payload={"permissions": [{"resource": "users", "action": "write"}]},
        )
    assert "core role permissions are protected" in str(core_error.value).lower()

    catalog = await list_permission_catalog()
    assert {"resource": "users", "action": "read", "enforced": True} in catalog
    assert {"resource": "api_keys", "action": "self_write", "enforced": True} in catalog
    assert {"resource": "auth", "action": "login", "enforced": True} in catalog
    assert {"resource": "tools", "action": "execute", "enforced": False} in catalog
    assert {"resource": "source_control", "action": "write", "enforced": False} in catalog


@pytest.mark.asyncio
async def test_admin_role_panel_api(client, auth_headers):
    created = await client.post(
        "/admin/chat/api/panel/roles",
        json={"name": "qa-reviewer", "description": "Reviews quality gates"},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["name"] == "qa-reviewer"

    listed = await client.get("/admin/chat/api/panel/roles", headers=auth_headers)
    assert listed.status_code == 200
    listed_role = next(role for role in listed.json() if role["name"] == "qa-reviewer")
    assert listed_role["assigned_users"] == []

    updated = await client.put(
        f"/admin/chat/api/panel/roles/{payload['id']}",
        json={"description": "Updated quality gate reviewer"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Updated quality gate reviewer"

    deleted = await client.delete(
        f"/admin/chat/api/panel/roles/{payload['id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_admin_role_permission_panel_api(client, auth_headers):
    catalog = await client.get("/admin/chat/api/panel/role-permission-catalog", headers=auth_headers)
    assert catalog.status_code == 200, catalog.text
    assert {"resource": "users", "action": "read", "enforced": True} in catalog.json()
    assert {"resource": "api_keys", "action": "self_read", "enforced": True} in catalog.json()
    assert {"resource": "auth", "action": "login", "enforced": True} in catalog.json()
    assert {"resource": "tools", "action": "execute", "enforced": False} in catalog.json()

    created = await client.post(
        "/admin/chat/api/panel/roles",
        json={
            "name": "project-reader",
            "description": "Reads project configuration",
            "permissions": [{"resource": "projects", "action": "read"}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    role = created.json()
    assert role["permissions"] == [{"resource": "projects", "action": "read"}]

    updated = await client.put(
        f"/admin/chat/api/panel/roles/{role['id']}",
        json={"permissions": [{"resource": "projects", "action": "write"}]},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["permissions"] == [{"resource": "projects", "action": "write"}]
