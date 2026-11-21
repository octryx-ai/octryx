"""Octryx Mobile "live": the owner's client, logged in interactively by cookie."""

from __future__ import annotations

import pytest

from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE
from tests.conftest import ADMIN_PASSWORD


@pytest.fixture
async def cookie_client(client):
    login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    client.cookies.set(ACCESS_TOKEN_COOKIE, login.json()["access_token"])
    yield client
    client.cookies.clear()
