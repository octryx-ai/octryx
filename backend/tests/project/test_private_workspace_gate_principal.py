from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE
from app.models import APIKey, Role, UserRole
from app.services.api_key.service import _hash_api_key, generate_api_key_value
from app.services.auth import create_access_token
from tests.devices.device_support import user_named
from tests.policy_engine_support import bearer
from tests.project.test_private_workspace_gate import _admin, _answers, _workspaces

pytestmark = pytest.mark.asyncio

PANEL_CONFIG = "/admin/chat/api/panel/projects/{id}/config"


def _cookie(user_id: str) -> dict[str, str]:
    return {"Cookie": f"{ACCESS_TOKEN_COOKIE}={create_access_token(user_id)}"}


async def _api_key(db, user_id: str) -> dict[str, str]:
    raw, prefix = generate_api_key_value()
    db.add(APIKey(user_id=user_id, key_hash=_hash_api_key(raw), key_prefix=prefix, name="gate", scopes=[]))
    await db.commit()
    return {"X-API-Key": raw}


async def _callers(db) -> tuple[str, str]:
    outsider = await user_named(db, f"gate-outsider-{uuid.uuid4().hex[:6]}")
    admin = await _admin(db)
    await db.commit()
    return admin.id, outsider.id


async def test_conflicting_credentials_answer_for_the_principal_the_route_authenticates(client, db):
    _owner, workspaces, sessions = await _workspaces(db)
    admin, outsider = await _callers(db)
    named = {kind: workspaces[kind] for kind in ("private", "unknown")}
    cases = [
        (PANEL_CONFIG, named, {**_cookie(admin), **bearer(outsider)}, 404),
        (PANEL_CONFIG, named, {**_cookie(admin), **await _api_key(db, outsider)}, 404),
        (PANEL_CONFIG, named, {**bearer(outsider), **await _api_key(db, admin)}, 403),
    ]
    for route, ids, headers, status in cases:
        answers = await _answers(client, route, ids, headers)
        assert answers["private"][0] == status, (route, sorted(headers), answers)
        assert answers["private"] == answers["unknown"], (route, sorted(headers), answers)


async def test_a_deactivated_admin_gets_the_same_401_for_every_id(client, db):
    _owner, workspaces, sessions = await _workspaces(db)
    admin = await user_named(db, f"gate-retired-admin-{uuid.uuid4().hex[:6]}")
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=admin.id, role_id=admin_role.id))
    admin.is_active = False
    await db.commit()
    named = {kind: workspaces[kind] for kind in ("private", "unknown")}
    for route, ids, headers in ((PANEL_CONFIG, named, _cookie(admin.id)), (PANEL_CONFIG, named, bearer(admin.id))):
        answers = await _answers(client, route, ids, headers)
        assert answers["private"][0] == 401 and answers["private"] == answers["unknown"], (route, answers)


async def test_an_interactive_admin_closes_a_live_terminal_session(client, db, auth_headers, monkeypatch):
    from app.http_setup import configure_http
    from app.main import app as main_app
    from app.runtime_toggles import ENABLE_HOST_TERMINAL_ENV
    from app.services.pty import service as pty_service

    monkeypatch.setenv(ENABLE_HOST_TERMINAL_ENV, "1")
    app = FastAPI()
    app.state.async_session_factory = main_app.state.async_session_factory
    configure_http(app, static_dir=Path("/nonexistent-static"))
    app.dependency_overrides = main_app.dependency_overrides
    closed: list[str] = []
    monkeypatch.setattr(pty_service.pty_manager, "get", lambda session_id: object() if session_id == "pty-1" else None)
    monkeypatch.setattr(pty_service.pty_manager, "close", closed.append)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as terminal_client:
        response = await terminal_client.delete("/api/v1/terminal/sessions/pty-1", headers=auth_headers)
    assert (response.status_code, response.json(), closed) == (200, {"status": "closed"}, ["pty-1"]), response.text
