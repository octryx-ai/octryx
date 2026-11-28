"""The admin host terminal (``/api/v1/terminal``) is off unless an operator switches it on, and even
then only an admin's own login opens it, never an API key: it is a shell on the host that reads every Workspace."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.models import APIKey
from app.runtime_toggles import ENABLE_HOST_TERMINAL_ENV, host_terminal_enabled
from app.services.api_key.service import _hash_api_key, generate_api_key_value


def _terminal_paths(app) -> list[str]:
    return [route.path for route in app.routes if isinstance(route, APIRoute) and route.path.startswith("/api/v1/terminal")]


def test_the_switch_is_off_by_default():
    assert host_terminal_enabled(env={}) is False
    assert host_terminal_enabled(env={ENABLE_HOST_TERMINAL_ENV: "1"}) is True


@pytest.mark.asyncio
async def test_the_terminal_is_not_served_by_default(client):
    from app.main import app

    assert _terminal_paths(app) == []
    assert (await client.get("/api/v1/terminal/sessions")).status_code == 404


@pytest.mark.asyncio
async def test_switched_on_an_admin_api_key_is_refused_and_the_admin_login_passes(client, db, auth_headers, auth_user):
    from app.api.routes.devices import terminal as terminal_api
    from app.main import app as main_app

    app = FastAPI()  # the router as a switched-on instance serves it; ``client`` set the test database overrides
    app.include_router(terminal_api.router)
    app.dependency_overrides = main_app.dependency_overrides
    raw, prefix = generate_api_key_value()
    db.add(APIKey(user_id=auth_user.id, key_hash=_hash_api_key(raw), key_prefix=prefix, name="ci", scopes=["knowledge:read"]))
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        refused = await client.get("/api/v1/terminal/sessions", headers={"X-API-Key": raw})
        allowed = await client.get("/api/v1/terminal/sessions", headers=auth_headers)
    assert refused.status_code == 403
    assert allowed.status_code == 200
