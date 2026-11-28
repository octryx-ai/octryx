from __future__ import annotations

import secrets
import uuid

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from sqlalchemy import select

from app.auth_cookie_policy import ACCESS_TOKEN_COOKIE
from app.main import app
from app.middleware.security.rate_limit import clear_rate_limit_buckets
from app.models import APIKey, Role, User, UserRole
from app.services.api_key.service import _hash_api_key, generate_api_key_value
from app.services.auth.tokens import create_access_token, hash_password
from app.services.auth_rate_limit import clear_all_auth_rate_limits
from app.web._helpers.admin_surface_gate import (
    ADMIN_ROLE_REQUIRED_DETAIL,
    api_admin_surface_gate,
    enforces_admin_itself,
    is_admin_surface_path,
    requires_admin_capability,
    requires_global_admin,
    web_admin_surface_gate,
)
from app.web._helpers.route_principal import RoutePrincipal, depends_on, route_principal

pytestmark = pytest.mark.asyncio

ORIGIN = {"Origin": "http://test"}
API_ADMIN = ("PUT", "/api/v1/admin/code-style")
API_ROOT_ADMIN = ("POST", "/api/v1/projects")
PANEL = ("POST", "/admin/chat/api/panel/exec-policies")
CHAT_PANEL = ("POST", "/chat/api/panel/exec-policies")
PAGE = ("POST", "/admin/plugins/reload")
WEB_ROOT_ADMIN = ("POST", "/budget-policies")
LOGIN_PASSWORD = secrets.token_urlsafe(16)  # random per run, never a literal


async def _user(db, role_name: str) -> User:
    name = f"gate-{role_name}-{uuid.uuid4().hex[:8]}"
    user = User(username=name, email=f"{name}@example.invalid", password_hash=hash_password(LOGIN_PASSWORD),
                display_name=name, is_active=True)
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


def _cookie(user: User) -> dict[str, str]:
    return {"Cookie": f"{ACCESS_TOKEN_COOKIE}={create_access_token(user.id)}"}


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _api_key(db, user: User) -> dict[str, str]:
    raw, prefix = generate_api_key_value()
    db.add(APIKey(user_id=user.id, key_hash=_hash_api_key(raw), key_prefix=prefix, name="gate", scopes=[]))
    await db.commit()
    return {"X-API-Key": raw}


async def _send(client, route: tuple[str, str], headers: dict[str, str]):
    clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    client.cookies.clear()
    method, path = route
    return await client.request(method, path, headers={**ORIGIN, **headers})


def _refused(response) -> bool:
    return response.status_code == 403 and response.json().get("detail") == ADMIN_ROLE_REQUIRED_DETAIL


async def test_the_gate_decides_for_the_credential_the_route_authenticates(client, db):
    admin, viewer = await _user(db, "admin"), await _user(db, "viewer")
    admin_key, viewer_key = await _api_key(db, admin), await _api_key(db, viewer)
    cases = [
        (API_ADMIN, {**_cookie(admin), **_bearer(viewer)}, False),
        (API_ADMIN, {**_cookie(admin), **viewer_key}, False),
        (API_ADMIN, {**_cookie(viewer), **admin_key}, True),
        (API_ADMIN, {**_cookie(viewer), **_bearer(admin)}, True),
        (API_ROOT_ADMIN, {**_cookie(admin), **_bearer(viewer)}, False),
        (API_ROOT_ADMIN, {**_cookie(viewer), **admin_key}, True),
        (PANEL, {**_cookie(viewer), **admin_key}, False),
        (PANEL, {**_cookie(viewer), **_bearer(admin)}, False),
        (PANEL, {**_cookie(admin), **_bearer(viewer)}, True),
        (CHAT_PANEL, {**_cookie(viewer), **admin_key}, False),
        (CHAT_PANEL, {**_bearer(viewer), **admin_key}, False),
        (WEB_ROOT_ADMIN, {**_cookie(viewer), **admin_key}, False),
        (WEB_ROOT_ADMIN, {**_cookie(admin), **viewer_key}, True),
    ]
    wrong = []
    for route, headers, admitted in cases:
        response = await _send(client, route, headers)
        if _refused(response) == admitted or response.status_code == 401:
            wrong.append((route, sorted(headers), admitted, response.status_code, response.text[:120]))
    assert wrong == []


async def test_an_admin_passes_and_a_viewer_is_refused_on_every_surface(client, db):
    admin, viewer = await _user(db, "admin"), await _user(db, "viewer")
    surfaces = [(API_ADMIN, _bearer), (API_ADMIN, _cookie), (API_ROOT_ADMIN, _bearer), (PANEL, _cookie),
                (CHAT_PANEL, _cookie), (CHAT_PANEL, _bearer), (PAGE, _cookie), (WEB_ROOT_ADMIN, _cookie)]
    for route, credential in surfaces:
        admitted = await _send(client, route, credential(admin))
        assert admitted.status_code not in (401, 403), (route, credential.__name__, admitted.text[:200])
        assert _refused(await _send(client, route, credential(viewer))), (route, credential.__name__)
    page_anonymous = await _send(client, PAGE, {})
    assert (page_anonymous.status_code, page_anonymous.headers.get("location")) == (303, "/chat/login")
    for route in (API_ADMIN, API_ROOT_ADMIN, PANEL, CHAT_PANEL, WEB_ROOT_ADMIN):
        assert (await _send(client, route, {})).status_code == 401, route


async def test_an_admin_signed_in_with_a_password_reaches_the_admin_pages_and_apis(client, db):
    admin = await _user(db, "admin")
    clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    signed_in = await client.post("/admin/login", headers=ORIGIN,
                                  data={"username": admin.username, "password": LOGIN_PASSWORD})
    assert signed_in.status_code == 303, signed_in.text
    assert client.cookies.get(ACCESS_TOKEN_COOKIE)
    assert (await client.get("/admin/plugins")).status_code == 200
    assert (await client.get("/api/v1/admin/code-style")).status_code == 200
    for method, path in (PANEL, API_ADMIN):
        response = await client.request(method, path, headers=ORIGIN, json={})
        assert response.status_code not in (401, 403), (path, response.text[:200])


def test_every_gated_route_carries_the_gate_of_its_own_principal():
    gates = {RoutePrincipal.API: api_admin_surface_gate, RoutePrincipal.WEB: web_admin_surface_gate}
    unmatched = []
    for route in app.routes:
        if isinstance(route, APIWebSocketRoute):
            assert not is_admin_surface_path(route.path), route.path
        if not isinstance(route, APIRoute) or enforces_admin_itself(route):
            continue
        if not any(requires_admin_capability(m, route.path) or requires_global_admin(m, route.path)
                   for m in route.methods):
            continue
        principal = route_principal(route)
        if principal not in gates or not depends_on(route, gates[principal]):
            unmatched.append((route.path, principal))
    assert unmatched == []
