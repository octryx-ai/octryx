"""Logout, refresh and expired or deactivated tokens, registration and user role management."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, User
from app.services.auth import create_access_token
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client, db):
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]

    logout_resp = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["refresh_token_revoked"] is True

    refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 401

    actions = (
        await db.execute(
            select(AuditLog.action).where(
                AuditLog.action.in_(["auth.refresh_token.revoked", "auth.logout.succeeded"])
            )
        )
    ).scalars().all()
    assert "auth.refresh_token.revoked" in actions
    assert "auth.logout.succeeded" in actions


@pytest.mark.asyncio
async def test_refresh_records_audit_event(client, db):
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]

    refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 200

    row = (
        await db.execute(select(AuditLog).where(AuditLog.action == "auth.refresh.succeeded"))
    ).scalar_one()
    assert row.details == {"method": "refresh_token"}
    assert row.resource_type == "auth"


@pytest.mark.asyncio
async def test_expired_access_token_cannot_access_protected_route(client):
    expired_token = create_access_token("expired-user", expires_delta=timedelta(seconds=-1))

    resp = await client.get("/api/v1/auth/whoami", headers={"Authorization": f"Bearer {expired_token}"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_deactivated_user_existing_access_token_is_rejected(client, auth_headers, db):
    create_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "token_lifecycle_user",
            "email": "token-lifecycle@example.com",
            "password": "password123",
            "display_name": "Token Lifecycle User",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 200
    user_id = create_resp.json()["id"]
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "token_lifecycle_user", "password": "password123"},
    )
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]

    deactivate_resp = await client.delete(f"/api/v1/auth/{user_id}", headers=auth_headers)
    assert deactivate_resp.status_code == 204

    whoami_resp = await client.get("/api/v1/auth/whoami", headers={"Authorization": f"Bearer {access_token}"})
    assert whoami_resp.status_code == 401

    denied = (
        await db.execute(
            select(AuditLog).where(AuditLog.user_id == user_id, AuditLog.action == "auth.access.denied")
        )
    ).scalar_one()
    assert denied.details["reason"] == "inactive_user"


@pytest.mark.asyncio
async def test_whoami_unauthorized(client):
    resp = await client.get("/api/v1/auth/whoami")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register(client, auth_headers):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "testpass123",
            "display_name": "Test User",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_get_user(client, auth_headers, db):
    result = await db.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one()

    resp = await client.get(f"/api/v1/auth/{admin.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert "admin" in data["roles"]


@pytest.mark.asyncio
async def test_update_user_roles(client, auth_headers):
    create_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "roleuser",
            "email": "roleuser@example.com",
            "password": "testpass123",
            "display_name": "Role User",
        },
        headers=auth_headers,
    )
    user_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/auth/{user_id}",
        json={"roles": ["operator"]},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["username"] == "roleuser"
    assert data["roles"] == ["operator"]
