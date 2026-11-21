"""Admin panel APIs for roles, users and user API keys enforce custom RBAC permissions."""

import pytest

from app.services.admin.governance.admin_role_service import create_role
from app.services.admin.governance.admin_user_service import create_user
from tests.admin_role_management_support import _auth_headers_for


@pytest.mark.asyncio
async def test_admin_panel_roles_api_enforces_custom_rbac_permissions(client, db):
    reader_role = await create_role(
        db,
        payload={
            "name": "role-reader",
            "description": "Reads role catalog",
            "permissions": [
                {"resource": "roles", "action": "read"},
                {"resource": "auth", "action": "login"},
            ],
        },
    )
    await create_user(
        db,
        payload={
            "username": "role_reader",
            "email": "role-reader@example.com",
            "password": "password123",
            "roles": [reader_role["name"]],
        },
    )
    await db.commit()
    headers = await _auth_headers_for(client, "role_reader")

    listed = await client.get("/admin/chat/api/panel/roles", headers=headers)
    assert listed.status_code == 200, listed.text

    denied = await client.post(
        "/admin/chat/api/panel/roles",
        json={"name": "denied-role", "description": "Should not be created"},
        headers=headers,
    )
    assert denied.status_code == 403, denied.text
    assert "roles:write" in denied.text


@pytest.mark.asyncio
async def test_admin_panel_users_api_enforces_custom_rbac_permissions(client, db):
    writer_role = await create_role(
        db,
        payload={
            "name": "user-writer",
            "description": "Manages users",
            "permissions": [
                {"resource": "users", "action": "read"},
                {"resource": "users", "action": "write"},
                {"resource": "auth", "action": "login"},
            ],
        },
    )
    await create_user(
        db,
        payload={
            "username": "user_writer",
            "email": "user-writer@example.com",
            "password": "password123",
            "roles": [writer_role["name"]],
        },
    )
    await db.commit()
    headers = await _auth_headers_for(client, "user_writer")

    listed = await client.get("/admin/chat/api/panel/users", headers=headers)
    assert listed.status_code == 200, listed.text

    created = await client.post(
        "/admin/chat/api/panel/users",
        json={
            "username": "rbac_created_user",
            "email": "rbac-created@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    assert created.json()["username"] == "rbac_created_user"


@pytest.mark.asyncio
async def test_admin_panel_user_api_key_management_is_permission_gated(client, db):
    key_admin_role = await create_role(
        db,
        payload={
            "name": "key-admin",
            "description": "Manages user API keys",
            "permissions": [
                {"resource": "api_keys", "action": "read"},
                {"resource": "api_keys", "action": "write"},
                {"resource": "auth", "action": "login"},
            ],
        },
    )
    await create_user(
        db,
        payload={
            "username": "key_admin",
            "email": "key-admin@example.com",
            "password": "password123",
            "roles": [key_admin_role["name"]],
        },
    )
    target = await create_user(
        db,
        payload={
            "username": "key_target",
            "email": "key-target@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    await db.commit()
    headers = await _auth_headers_for(client, "key_admin")

    # A key minted for a person would act as them (private Workspace included): refused.
    refused = await client.post(
        f"/admin/chat/api/panel/users/{target['id']}/api-keys",
        json={"name": "automation", "scopes": ["sessions:write"]},
        headers=headers,
    )
    assert refused.status_code == 403 and refused.json()["reason"] == "api_key_for_other_user"
    # A technical (service) account still gets its keys from a key admin.
    from app.models import User as UserModel

    service_account = await db.get(UserModel, target["id"])
    service_account.account_type = "technical"
    await db.commit()
    created = await client.post(
        f"/admin/chat/api/panel/users/{target['id']}/api-keys",
        json={"name": "automation", "scopes": ["sessions:write"]},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["api_key"].startswith("oek_")
    assert payload["key_prefix"] == payload["api_key"][:12]

    listed = await client.get(f"/admin/chat/api/panel/users/{target['id']}/api-keys", headers=headers)
    assert listed.status_code == 200, listed.text
    listed_payload = listed.json()
    assert listed_payload[0]["id"] == payload["id"]
    assert "api_key" not in listed_payload[0]

    revoked = await client.delete(
        f"/admin/chat/api/panel/users/{target['id']}/api-keys/{payload['id']}",
        headers=headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None


@pytest.mark.asyncio
async def test_admin_panel_user_api_key_management_denies_without_permission(client, db):
    target = await create_user(
        db,
        payload={
            "username": "no_key_target",
            "email": "no-key-target@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    await create_user(
        db,
        payload={
            "username": "no_key_admin",
            "email": "no-key-admin@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )
    await db.commit()
    headers = await _auth_headers_for(client, "no_key_admin")

    response = await client.get(f"/admin/chat/api/panel/users/{target['id']}/api-keys", headers=headers)
    assert response.status_code == 403, response.text
    assert "api_keys:read" in response.text
