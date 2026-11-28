"""The admin user service: role validation, technical users, profile and status updates, deactivation and login policy."""

import pytest
from sqlalchemy import select

from app.models import APIKey, RefreshToken
from app.services.admin.governance.admin_role_service import create_role
from app.services.admin.governance.admin_user_service import create_user, reset_user_password, update_user


@pytest.mark.asyncio
async def test_admin_user_service_rejects_unknown_roles(db):
    with pytest.raises(Exception) as error:
        await create_user(
            db,
            payload={
                "username": "bad_role_user",
                "email": "bad-role@example.com",
                "password": "password123",
                "roles": ["does-not-exist"],
            },
        )
    assert "unknown role" in str(error.value).lower()


@pytest.mark.asyncio
async def test_admin_user_service_keeps_every_assigned_role(db, auth_user):
    created = await create_user(
        db,
        payload={
            "username": "multi_role_user",
            "email": "multi-role@example.com",
            "password": "password123",
            "roles": ["viewer", "operator", "viewer"],
        },
    )
    assert sorted(created["roles"]) == ["operator", "viewer"]

    updated = await update_user(
        db, admin_id=auth_user.id, user_id=created["id"], payload={"roles": ["operator", "technical", "viewer"]}
    )
    assert sorted(updated["roles"]) == ["operator", "technical", "viewer"]


@pytest.mark.asyncio
async def test_admin_user_service_creates_technical_user_with_technical_role(db):
    user = await create_user(
        db,
        payload={
            "username": "technical_runner",
            "email": "technical-runner@example.com",
            "password": "password123",
            "account_type": "technical",
        },
    )

    assert user["account_type"] == "technical"
    assert user["roles"] == ["technical"]


@pytest.mark.asyncio
async def test_admin_user_service_updates_profile_status_and_password(db):
    user = await create_user(
        db,
        payload={
            "username": "identity_user",
            "email": "identity-user@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
    )

    updated = await update_user(
        db,
        admin_id="admin",
        user_id=user["id"],
        payload={
            "username": "identity_editor",
            "email": "identity-editor@example.com",
            "display_name": "Identity Editor",
            "is_active": False,
        },
    )
    assert updated["username"] == "identity_editor"
    assert updated["email"] == "identity-editor@example.com"
    assert updated["display_name"] == "Identity Editor"
    assert updated["is_active"] is False

    reactivated = await update_user(
        db,
        admin_id="admin",
        user_id=user["id"],
        payload={"is_active": True},
    )
    assert reactivated["is_active"] is True

    reset = await reset_user_password(
        db,
        admin_id="admin",
        user_id=user["id"],
        password="new-password-123",
    )
    assert reset["status"] == "password_reset"
    assert reset["user_id"] == user["id"]


@pytest.mark.asyncio
async def test_admin_user_deactivation_revokes_refresh_tokens_and_api_keys(client, auth_headers, db):
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "disable-auth-material",
            "email": "disable-auth-material@example.com",
            "password": "password123",
            "display_name": "Disable Auth Material",
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    user_id = created.json()["id"]

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "disable-auth-material", "password": "password123"},
    )
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    refresh_token = login.json()["refresh_token"]

    api_key = await client.post(
        "/api/v1/api-keys",
        json={"name": "User key", "scopes": ["knowledge:read"]},
        headers=user_headers,
    )
    assert api_key.status_code == 201, api_key.text

    deactivated = await client.delete(f"/admin/chat/api/panel/users/{user_id}", headers=auth_headers)
    assert deactivated.status_code == 200, deactivated.text

    refresh_rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))).scalars().all()
    api_key_rows = (await db.execute(select(APIKey).where(APIKey.user_id == user_id))).scalars().all()
    assert refresh_rows and all(row.revoked_at is not None for row in refresh_rows)
    assert api_key_rows and all(row.revoked_at is not None for row in api_key_rows)

    refresh_again = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_again.status_code == 401
    api_key_again = await client.get("/api/v1/auth/whoami", headers={"X-API-Key": api_key.json()["api_key"]})
    assert api_key_again.status_code == 401


@pytest.mark.asyncio
async def test_admin_role_change_affects_login_policy_predictably(client, auth_headers, db):
    role = await create_role(
        db,
        payload={
            "name": "no-login-role",
            "description": "Cannot log in",
            "permissions": [{"resource": "knowledge", "action": "read"}],
        },
    )
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "role-change-login",
            "email": "role-change-login@example.com",
            "password": "password123",
            "display_name": "Role Change Login",
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    user_id = created.json()["id"]

    updated = await update_user(db, admin_id="admin", user_id=user_id, payload={"roles": [role["name"]]})
    assert updated["roles"] == [role["name"]]

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "role-change-login", "password": "password123"},
    )
    assert login.status_code == 403
    assert "Login is not permitted" in login.text


@pytest.mark.asyncio
async def test_admin_user_panel_api_updates_status_and_resets_password(client, auth_headers):
    created = await client.post(
        "/admin/chat/api/panel/users",
        json={
            "username": "panel_identity_user",
            "email": "panel-identity@example.com",
            "password": "password123",
            "roles": ["viewer"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    user = created.json()

    updated = await client.put(
        f"/admin/chat/api/panel/users/{user['id']}",
        json={
            "username": "panel_identity_editor",
            "email": "panel-identity-editor@example.com",
            "display_name": "Panel Identity Editor",
            "is_active": False,
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["username"] == "panel_identity_editor"
    assert updated.json()["is_active"] is False

    reactivated = await client.put(
        f"/admin/chat/api/panel/users/{user['id']}",
        json={"is_active": True},
        headers=auth_headers,
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["is_active"] is True

    reset = await client.post(
        f"/admin/chat/api/panel/users/{user['id']}/reset-password",
        json={"password": "new-password-123"},
        headers=auth_headers,
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["status"] == "password_reset"
