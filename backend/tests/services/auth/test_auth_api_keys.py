"""API key creation, scopes, project binding, self-service keys and invalid keys."""

import pytest
from sqlalchemy import select

from app.models import APIKey, Permission, Project, Role, User, UserRole
from app.services.auth import hash_password


@pytest.mark.asyncio
async def test_api_key_crud_and_auth_alternative(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    create_resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "CI pipeline",
            "project_id": project.id,
            "scopes": ["sessions:read", "tasks:trigger"],
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "CI pipeline"
    assert created["project_id"] == project.id
    assert created["scopes"] == ["sessions:read", "tasks:trigger"]
    assert created["api_key"].startswith("oek_")

    list_resp = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert any(entry["id"] == created["id"] for entry in listed)

    api_key_headers = {"X-API-Key": created["api_key"]}
    whoami_resp = await client.get("/api/v1/auth/whoami", headers=api_key_headers)
    assert whoami_resp.status_code == 200
    assert whoami_resp.json()["username"] == "admin"

    refreshed = await db.get(APIKey, created["id"])
    assert refreshed is not None
    assert refreshed.last_used_at is not None

    projects_resp = await client.get("/api/v1/projects", headers=api_key_headers)
    assert projects_resp.status_code == 200

    delete_resp = await client.delete(f"/api/v1/api-keys/{created['id']}", headers=auth_headers)
    assert delete_resp.status_code == 200

    whoami_after_revoke = await client.get("/api/v1/auth/whoami", headers=api_key_headers)
    assert whoami_after_revoke.status_code == 401
    assert whoami_after_revoke.json()["error"] == "API key revoked"


@pytest.mark.asyncio
async def test_api_key_accepts_mcp_knowledge_scopes(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    create_resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Knowledge MCP",
            "project_id": project.id,
            "scopes": [
                "MCP:Knowledge:Read",
                "knowledge:read",
                "engineering_packs:read",
                "knowledge:read",
            ],
        },
        headers=auth_headers,
    )

    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["project_id"] == project.id
    assert created["scopes"] == [
        "mcp:knowledge:read",
        "knowledge:read",
        "engineering_packs:read",
    ]
    assert created["api_key"].startswith("oek_")

    stored = await db.get(APIKey, created["id"])
    assert stored is not None
    assert stored.key_hash != created["api_key"]


@pytest.mark.asyncio
async def test_api_key_rejects_unsupported_scope(client, auth_headers):
    create_resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "Unsupported scope", "scopes": ["mcp:knowledge:write"]},
        headers=auth_headers,
    )

    assert create_resp.status_code == 422
    assert "Unsupported API key scope" in create_resp.text


@pytest.mark.asyncio
async def test_non_admin_api_key_project_binding_requires_project_access(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_user = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "viewer-project-key-user",
            "email": "viewer-project-key-user@example.com",
            "password": "testpass123",
            "display_name": "Viewer Project Key User",
        },
        headers=auth_headers,
    )
    assert create_user.status_code == 200, create_user.text

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "viewer-project-key-user", "password": "testpass123"},
    )
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    create_key = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Project-bound MCP key",
            "project_id": project.id,
            "scopes": ["mcp:knowledge:read", "knowledge:read"],
        },
        headers=user_headers,
    )

    assert create_key.status_code == 404  # a non-member gets the answer of an unknown Workspace
    assert create_key.json()["detail"]["code"] == "project_not_found"


@pytest.mark.asyncio
async def test_viewer_can_create_self_api_key(client, auth_headers):
    create_user = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "viewer-key-user",
            "email": "viewer-key-user@example.com",
            "password": "testpass123",
            "display_name": "Viewer Key User",
        },
        headers=auth_headers,
    )
    assert create_user.status_code == 200, create_user.text

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "viewer-key-user", "password": "testpass123"},
    )
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    create_key = await client.post(
        "/api/v1/api-keys",
        json={"name": "Self-service key"},
        headers=user_headers,
    )

    assert create_key.status_code == 201, create_key.text
    assert create_key.json()["api_key"].startswith("oek_")


@pytest.mark.asyncio
async def test_self_api_key_routes_require_self_permissions(client, db):
    role = Role(name="login-only", description="Can login but cannot manage own keys")
    db.add(role)
    await db.flush()
    db.add(Permission(role_id=role.id, resource="auth", action="login"))
    user = User(
        username="login-only-user",
        email="login-only-user@example.com",
        password_hash=hash_password("testpass123"),
        display_name="Login Only User",
        account_type="human",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "login-only-user", "password": "testpass123"},
    )
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    list_keys = await client.get("/api/v1/api-keys", headers=user_headers)
    create_key = await client.post(
        "/api/v1/api-keys",
        json={"name": "Blocked key"},
        headers=user_headers,
    )

    assert list_keys.status_code == 403
    assert create_key.status_code == 403


@pytest.mark.asyncio
async def test_invalid_api_key_returns_unauthorized(client):
    resp = await client.get("/api/v1/auth/whoami", headers={"X-API-Key": "oek_invalid"})
    assert resp.status_code == 401
    payload = resp.json()
    assert payload["error"] == "Invalid API key"
    assert payload["status_code"] == 401
