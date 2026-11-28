"""Contract: every admin mutation requires an admin, and a new one fails closed unless it is on the reasoned
user-level allowlist."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.main import app
from app.middleware.security.rate_limit import clear_rate_limit_buckets
from app.models import Project, Role, Session, SessionAccess, User, UserProject, UserRole
from app.services.admin.governance.admin_access_service import is_admin_capable
from app.services.auth.tokens import create_access_token, hash_password
from app.services.auth_rate_limit import clear_all_auth_rate_limits
from app.web._helpers.admin_surface_gate import (
    enforces_admin_itself,
    is_admin_surface_path,
    requires_admin_capability,
    requires_global_admin,
)
from app.web._helpers.admin_surface_root_routes import ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH
from app.web._helpers.admin_surface_user_routes import USER_LEVEL_ADMIN_SURFACE_ROUTES

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
GLOBAL_ADMIN_GUARDS = frozenset(
    {"_require_admin", "_require_admin_api", "require_admin_user", "require_global_admin", "require_page_admin"}
)
ADMIN_DETAILS = {"Admin role required", "Admin access required"}

API_ADMIN_MUTATIONS = [
    ("POST", "/api/v1/providers"),
    ("POST", "/api/v1/providers/probe-x/models/sync"),
    ("POST", "/api/v1/packages/export"),
    ("POST", "/api/v1/packages/import"),
    ("POST", "/api/v1/webhooks"),
    ("POST", "/api/v1/workers/projects/probe-x/autoscale/run"),
    ("POST", "/api/v1/call-agents/config"),
    ("PATCH", "/api/v1/call-agents/config/probe-x"),
    ("DELETE", "/api/v1/call-agents/config/probe-x"),
    ("POST", "/api/v1/call-agents/run"),
    ("POST", "/api/v1/speakers/enroll"),
    ("DELETE", "/api/v1/speakers/remove"),
    ("POST", "/api/v1/speakers/set-hf-token"),
]


def _served_admin_surface() -> list[tuple[str, str]]:
    served = []
    for route in app.routes:
        if isinstance(route, APIRoute) and is_admin_surface_path(route.path):
            served += [(method, route.path) for method in sorted(route.methods & MUTATING)]
    return served


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "probe-x", path)


async def _user(db, role_name: str = "viewer") -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=str(uuid.uuid4()),
        username=f"{role_name}-{suffix}",
        email=f"{role_name}-{suffix}@example.com",
        password_hash=hash_password("gate-Test-Pw-123"),
        display_name=role_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


async def _send(client, method: str, path: str, *, token: str | None):
    clear_rate_limit_buckets()
    clear_all_auth_rate_limits()
    client.cookies.clear()
    headers = {}
    if token:
        client.cookies.set("access_token", token)
        headers["Authorization"] = f"Bearer {token}"
    return await client.request(method, path, headers=headers)


def test_the_user_level_allowlist_is_exact_and_every_chat_entry_has_its_root_twin():
    served = set(_served_admin_surface())
    all_served = {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    assert USER_LEVEL_ADMIN_SURFACE_ROUTES <= served, sorted(USER_LEVEL_ADMIN_SURFACE_ROUTES - served)
    for method, path in USER_LEVEL_ADMIN_SURFACE_ROUTES - {("POST", "/admin/login")}:
        assert path.startswith("/admin/chat/")
        assert (method, path.removeprefix("/admin")) in all_served, (method, path)
    gated = [entry for entry in served if requires_admin_capability(*entry)]
    assert len(gated) == len(served) - len(USER_LEVEL_ADMIN_SURFACE_ROUTES)
    assert len(gated) > 200


@pytest.mark.asyncio
async def test_every_admin_surface_mutation_refuses_a_viewer_and_an_anonymous_caller(client, db):
    viewer = await _user(db)
    token = create_access_token(viewer.id)
    leaks = []
    for method, path in _served_admin_surface():
        if not requires_admin_capability(method, path):
            continue
        as_viewer = await _send(client, method, _concrete(path), token=token)
        anonymous = await _send(client, method, _concrete(path), token=None)
        login_redirect = anonymous.status_code == 303 and anonymous.headers.get("location") == "/chat/login"
        if as_viewer.status_code != 403 or not (anonymous.status_code == 401 or login_redirect):
            leaks.append((method, path, as_viewer.status_code, anonymous.status_code))
        elif as_viewer.json()["detail"] not in ADMIN_DETAILS:
            leaks.append((method, path, as_viewer.json()["detail"]))
    assert leaks == []


@pytest.mark.asyncio
async def test_legacy_admin_pages_and_api_admin_mutations_refuse_a_viewer(client, db):
    viewer = await _user(db)
    token = create_access_token(viewer.id)
    for path in ("/admin/plugins",):
        assert (await _send(client, "GET", path, token=token)).status_code == 403, path
    for method, path in API_ADMIN_MUTATIONS:
        response = await _send(client, method, path, token=token)
        assert response.status_code == 403, (method, path, response.status_code)
        assert response.json()["detail"] == "Admin access required"


def _handler_requires_global_admin(route: APIRoute) -> bool:
    try:
        function = ast.parse(textwrap.dedent(inspect.getsource(route.endpoint))).body[0]
    except (OSError, TypeError):
        return False
    for statement in function.body:
        call = getattr(statement, "value", None)
        call = call.value if isinstance(call, ast.Await) else call
        if isinstance(call, ast.Call):
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", "")
            if name in GLOBAL_ADMIN_GUARDS:
                return True
    return False


def test_admin_only_mutations_outside_the_admin_path_are_listed_exactly():
    served = {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    assert ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH <= served, sorted(ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH - served)
    guarded_in_handler = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        and not is_admin_surface_path(route.path)
        and not enforces_admin_itself(route)
        and _handler_requires_global_admin(route)
        for method in route.methods & MUTATING
    }
    assert ("POST", "/budget-policies") in guarded_in_handler
    assert guarded_in_handler == ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH
    assert all(requires_global_admin(*entry) for entry in ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH)


@pytest.mark.asyncio
async def test_admin_only_mutations_outside_the_admin_path_refuse_non_admins_before_the_body(client, db):
    viewer = await _user(db)
    workspace_admin = await _user(db)
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    db.add(UserProject(user_id=workspace_admin.id, project_id=project.id, role="admin"))
    await db.commit()
    tokens = [create_access_token(viewer.id), create_access_token(workspace_admin.id)]
    leaks = []
    for method, path in sorted(ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH):
        for token in tokens:
            refused = await _send(client, method, _concrete(path), token=token)
            if refused.status_code != 403 or refused.json().get("detail") != "Admin role required":
                leaks.append((method, path, refused.status_code))
        anonymous = await _send(client, method, _concrete(path), token=None)
        if anonymous.status_code != 401:
            leaks.append((method, path, "anonymous", anonymous.status_code))
    assert leaks == []
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    admitted = await _send(client, "POST", "/budget-policies", token=create_access_token(admin.id))
    assert admitted.status_code == 422


@pytest.mark.asyncio
async def test_admins_and_workspace_admins_are_admin_capable_and_a_viewer_is_not(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    viewer = await _user(db)
    workspace_admin = await _user(db)
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    db.add(UserProject(user_id=workspace_admin.id, project_id=project.id, role="admin"))
    await db.flush()
    assert await is_admin_capable(db, admin.id)
    assert await is_admin_capable(db, workspace_admin.id)
    assert not await is_admin_capable(db, viewer.id)


@pytest.mark.asyncio
async def test_platform_templates_and_session_grants_are_scoped(client, db):
    viewer = await _user(db)
    owner = await _user(db)
    token = create_access_token(viewer.id)

    platform_template = await client.post(
        "/api/v1/agent-chains/templates",
        json={"name": "viewer-platform-chain", "steps": [{"agent_type": "diagnosis"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert platform_template.status_code == 403

    session = Session(id=str(uuid.uuid4()), user_id=owner.id, agent_type="diagnosis", status="active")
    db.add(session)
    await db.commit()
    grant = await client.post(
        f"/api/v1/sessions/{session.id}/access",
        json={"user_id": viewer.id, "access_scope": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert grant.status_code == 404
    revoke = await client.delete(
        f"/api/v1/sessions/{session.id}/access/{owner.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert revoke.status_code == 404
    await db.rollback()
    grants = (await db.execute(select(SessionAccess).where(SessionAccess.session_id == session.id))).scalars().all()
    assert grants == []

    owner_token = create_access_token(owner.id)
    shared = await client.post(
        f"/api/v1/sessions/{session.id}/access",
        json={"user_id": viewer.id, "access_scope": "read"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert shared.status_code == 200
    escalate = await client.post(
        f"/api/v1/sessions/{session.id}/access",
        json={"user_id": viewer.id, "access_scope": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert escalate.status_code == 403
