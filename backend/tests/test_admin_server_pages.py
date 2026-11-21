"""The remaining server-rendered admin pages: login redirect when anonymous, the admin root, the settings page."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.web.routers.ui_pages as ui_pages_router
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_settings_page_redirects_to_login_when_unauthenticated(monkeypatch):
    async def unauthenticated_user(_request, _db):
        raise HTTPException(status_code=307, headers={"Location": "/admin/login"})

    monkeypatch.setattr(ui_pages_router, "_require_user", unauthenticated_user)

    request = Request({"type": "http", "method": "GET", "path": "/admin", "headers": []})

    response = await ui_pages_router.settings_page(request, db=None)
    assert response.status_code == 303
    assert response.headers["location"] == "/chat/login"


@pytest.mark.asyncio
async def test_admin_root_redirects_to_chat_and_settings_renders(client):
    login_response = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    response = await client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/chat"
    for path in ("/admin/agents", "/admin/tasks", "/admin/skills"):
        assert (await client.get(path, follow_redirects=False)).status_code == 404, path

    settings_response = await client.get("/admin/settings", follow_redirects=False)
    assert settings_response.status_code == 200
    assert "Archived Threads" in settings_response.text
