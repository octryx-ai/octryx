"""Tests for authentication endpoints."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, User, UserRole
from app.services.auth import hash_password
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_records_secret_safe_audit_events(client, db):
    failed = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert failed.status_code == 401

    success = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert success.status_code == 200

    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.action.in_(["auth.login.failed", "auth.login.succeeded"]))
            .order_by(AuditLog.created_at)
        )
    ).scalars().all()
    assert [row.action for row in rows] == ["auth.login.failed", "auth.login.succeeded"]
    assert rows[0].details["reason"] == "invalid_credentials"
    assert "password" not in rows[0].details
    assert rows[1].details["method"] == "password"


@pytest.mark.asyncio
async def test_login_requires_auth_login_permission(client, db):
    role = Role(name="login-blocked", description="No login permission")
    user = User(
        username="blocked-login",
        email="blocked-login@example.com",
        password_hash=hash_password("testpass123"),
        display_name="Blocked Login",
        account_type="human",
        is_active=True,
    )
    db.add_all([role, user])
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "blocked-login", "password": "testpass123"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"] == "Login is not permitted for this user"


@pytest.mark.asyncio
async def test_technical_user_cannot_password_login_by_default(client, db):
    technical_role = (await db.execute(select(Role).where(Role.name == "technical"))).scalar_one()
    user = User(
        username="technical-bot",
        email="technical-bot@example.com",
        password_hash=hash_password("testpass123"),
        display_name="Technical Bot",
        account_type="technical",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=technical_role.id))
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "technical-bot", "password": "testpass123"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"] == "Login is not permitted for this user"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "Invalid credentials"
    assert data["detail"] == "Invalid credentials"
    assert data["status_code"] == 401
    assert data["request_id"]


@pytest.mark.asyncio
async def test_login_unknown_user(client):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "unknown", "password": "test"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limited_after_five_failed_attempts(client):
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 429
    assert resp.headers["Retry-After"]
    data = resp.json()
    assert data["status_code"] == 429
    assert "Too many login attempts" in data["error"]
    assert data["request_id"]


@pytest.mark.asyncio
async def test_login_success_resets_failed_attempt_counter(client):
    for _ in range(3):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    success = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert success.status_code == 200

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_whoami(client, auth_headers):
    resp = await client.get("/api/v1/auth/whoami", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
