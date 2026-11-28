"""SSO-only sign-in is enforced on every password login path."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.system_config import set_system_config_value
from app.services.system_config.constants import AGENT_AUTH_LOGIN_MODE_KEY
from tests.conftest import ADMIN_PASSWORD


async def _enable_sso_only(db) -> None:
    await set_system_config_value(db, key=AGENT_AUTH_LOGIN_MODE_KEY, value="true")
    await db.commit()


@pytest.mark.asyncio
async def test_api_password_login_is_refused_when_sso_only(client, db):
    await _enable_sso_only(db)

    response = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})

    assert response.status_code == 403
    assert "access_token" not in response.text
    blocked = (
        await db.execute(select(AuditLog).where(AuditLog.action == "auth.login.blocked"))
    ).scalars().all()
    assert any((row.details or {}).get("reason") == "password_login_disabled" for row in blocked)


@pytest.mark.asyncio
async def test_api_password_login_refusal_does_not_reveal_password_validity(client, db):
    await _enable_sso_only(db)

    wrong = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "wrong"})
    right = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})

    assert wrong.status_code == right.status_code == 403
    assert {k: v for k, v in wrong.json().items() if k != "request_id"} == {
        k: v for k, v in right.json().items() if k != "request_id"
    }


@pytest.mark.asyncio
async def test_web_password_login_is_refused_when_sso_only(client, db):
    await _enable_sso_only(db)

    response = await client.post("/chat/login", data={"username": "admin", "password": ADMIN_PASSWORD})

    assert response.status_code == 403
    assert "access_token" not in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_api_password_login_still_works_without_sso_only(client):
    response = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})

    assert response.status_code == 200
