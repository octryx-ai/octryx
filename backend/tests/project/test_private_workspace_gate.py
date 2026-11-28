from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, SessionCollaborator, User
from app.services.project.private_workspace import ensure_private_workspace
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.policy_engine_support import bearer
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workspace_id_route_support import answer_text, stable_headers

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]

WORKSPACE_ROUTES = (
    "/api/v1/work-roles/workspaces/{id}/me",
    "/api/v1/admin/command-safety/workspaces/{id}",
    "/api/v1/workspaces/{id}/session-transcripts",
    "/chat/api/workflows?project_id={id}",
    "/admin/chat/api/panel/projects/{id}/config",
    "/admin/chat/api/panel/runtime-settings?project_id={id}",
)
SESSION_ROUTES = ("/api/v1/sessions/{id}", "/chat/api/sessions/{id}/view")
# A session that is not the caller's own is reported missing (``requestedSessionNotFound``), for admins too.
OWN_SESSION_READS = ("/chat/api/sessions/{id}/view", "/chat/api/bootstrap?session_id={id}",
                     "/admin/chat/api/sessions/{id}/view", "/admin/chat/api/bootstrap?session_id={id}")
# Each request is invalid in one more place than the Workspace it names.
INVALID_REQUESTS = (
    ("GET", "/api/v1/workspaces/{id}/session-transcripts?session_id=" + "x" * 37, None),
    ("PUT", "/api/v1/workers/projects/{id}/pool-config", {"min_workers": 0}),
    ("GET", "/admin/chat/api/panel/channels/not-a-number?project_id={id}", None),
)
SESSION_CONTENT_READS = ("/api/v1/sessions/{id}", "/api/v1/sessions/{id}/messages",
                         "/api/v1/sessions/{id}/export.pdf", "/api/v1/sessions/{id}/export.analysis.json",
                         "/api/v1/canvas/sessions/{id}")
WORKSPACE_LIMITS = "/admin/chat/api/panel/connectors/jira/workspace-limits"


async def _workspaces(db, owner: User | None = None) -> tuple[User, dict[str, str], dict[str, str]]:
    owner = owner or await user_named(db, f"gate-owner-{uuid.uuid4().hex[:6]}")
    private = await ensure_private_workspace(db, owner)
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=private.id, origin="chat")
    db.add(session)
    await db.commit()
    workspaces = {"private": private.id, "shared": await seed_workspace(db), "unknown": str(uuid.uuid4())}
    sessions = {"private": session.id, "unknown": str(uuid.uuid4())}
    await db.commit()
    return owner, workspaces, sessions


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _outsiders(db) -> dict[str, dict[str, str]]:
    outsider = await user_named(db, f"gate-outsider-{uuid.uuid4().hex[:6]}")
    admin = await _admin(db)
    await db.commit()
    return {"outsider": bearer(outsider.id), "platform admin": bearer(admin.id)}


def _answer(response, value: str) -> tuple:
    return response.status_code, answer_text(response, value), stable_headers(response, value)


async def _answers(client, route: str, named: dict[str, str], headers: dict[str, str], method: str = "GET",
                   body: dict | bytes | None = None) -> dict[str, tuple]:
    answers = {}
    for kind, value in named.items():
        if isinstance(body, bytes):
            sent = {"content": body, "headers": {**headers, "Content-Type": "application/json"}}
        else:
            sent = {"json": body, "headers": headers}
        answers[kind] = _answer(await client.request(method, route.format(id=value), **sent), value)
    return answers


async def test_without_credentials_every_workspace_id_gets_the_same_401(client, db):
    _owner, workspaces, sessions = await _workspaces(db)
    for route in WORKSPACE_ROUTES:
        answers = await _answers(client, route, workspaces, {})
        assert answers["private"][0] == 401, (route, answers)
        assert answers["private"] == answers["shared"] == answers["unknown"], (route, answers)
    for route in SESSION_ROUTES:
        answers = await _answers(client, route, sessions, {})
        assert answers["private"][0] == 401 and answers["private"] == answers["unknown"], (route, answers)


async def test_an_invalid_credential_gets_the_same_401_for_every_workspace_id(client, db):
    _owner, workspaces, _sessions = await _workspaces(db)
    for route in WORKSPACE_ROUTES:
        answers = await _answers(client, route, workspaces, bearer(str(uuid.uuid4())))
        assert answers["private"][0] == 401, (route, answers)
        assert answers["private"] == answers["shared"] == answers["unknown"], (route, answers)


async def test_a_non_member_gets_the_same_answer_for_a_private_and_an_unknown_workspace(client, db):
    _owner, workspaces, sessions = await _workspaces(db)
    outsiders = await _outsiders(db)
    named = {kind: workspaces[kind] for kind in ("private", "unknown")}
    cases = [("outsider", "/api/v1/work-roles/workspaces/{id}/me", named, 404),
             *[(caller, "/api/v1/sessions/{id}", sessions, 404) for caller in outsiders],
             *[(caller, route, sessions, 200) for caller in outsiders for route in OWN_SESSION_READS],
             *[("platform admin", route, named, 404) for route in WORKSPACE_ROUTES]]
    for caller, route, ids, status in cases:
        answers = await _answers(client, route, ids, outsiders[caller])
        assert answers["private"][0] == status, (caller, route, answers)
        assert answers["private"] == answers["unknown"], (caller, route, answers)


async def test_an_otherwise_invalid_request_answers_a_private_and_an_unknown_workspace_alike(client, db):
    _owner, workspaces, _sessions = await _workspaces(db)
    callers = {"anonymous": {}, **await _outsiders(db)}
    named = {kind: workspaces[kind] for kind in ("private", "unknown")}
    for caller, headers in callers.items():
        for method, route, body in INVALID_REQUESTS:
            answers = await _answers(client, route, named, headers, method, body)
            assert answers["private"][0] in (401, 404, 422), (caller, route, answers)
            assert answers["private"] == answers["unknown"], (caller, route, answers)


async def test_malformed_json_is_a_parse_error_whatever_workspace_it_names(client, db):
    _owner, workspaces, _sessions = await _workspaces(db)
    callers = {"anonymous": {}, **await _outsiders(db)}
    named = {kind: workspaces[kind] for kind in ("private", "unknown")}
    for caller, headers in callers.items():
        answers = await _answers(client, "/api/v1/workers/projects/{id}/pool-config", named, headers, "PUT", b"{")
        assert answers["private"][0] == 422 and answers["private"] == answers["unknown"], (caller, answers)


async def test_the_workspace_limits_batch_leaves_out_a_private_and_an_unknown_workspace_alike(client, db):
    _owner, workspaces, _sessions = await _workspaces(db)
    headers = (await _outsiders(db))["platform admin"]
    answers = {}
    for kind in ("private", "unknown"):
        response = await client.get(WORKSPACE_LIMITS, params=[("ids", workspaces["shared"]), ("ids", workspaces[kind])],
                                    headers=headers)
        answers[kind] = _answer(response, workspaces[kind])
    assert answers["private"][0] == 200 and answers["private"] == answers["unknown"], answers
    response = await client.get(WORKSPACE_LIMITS, params={"ids": workspaces["private"]}, headers=headers)
    assert response.json()["workspaces"] == [], response.text[:300]


async def test_the_owner_of_a_private_workspace_passes(client, db):
    owner, workspaces, sessions = await _workspaces(db)
    for route in ("/api/v1/work-roles/workspaces/{id}/me", "/api/v1/workspaces/{id}/session-transcripts"):
        response = await client.get(route.format(id=workspaces["private"]), headers=bearer(owner.id))
        assert response.status_code == 200, (route, response.text[:300])
    response = await client.get(f"/api/v1/sessions/{sessions['private']}", headers=bearer(owner.id))
    assert response.status_code == 200 and response.json()["id"] == sessions["private"], response.text[:300]


async def test_a_platform_admin_who_owns_the_private_workspace_passes(client, db, auth_user):
    _owner, workspaces, sessions = await _workspaces(db, owner=auth_user)
    for route in ("/admin/chat/api/panel/projects/{id}/config", "/api/v1/workspaces/{id}/session-transcripts",
                  "/admin/chat/api/panel/runtime-settings?project_id={id}"):
        response = await client.get(route.format(id=workspaces["private"]), headers=bearer(auth_user.id))
        assert response.status_code == 200, (route, response.text[:300])
    for route in SESSION_ROUTES:
        response = await client.get(route.format(id=sessions["private"]), headers=bearer(auth_user.id))
        assert response.status_code == 200, (route, response.text[:300])


async def test_a_session_share_opens_only_the_shared_sessions_content(client, db):
    from app.services.canvas import canvas_manager

    owner, _named, sessions = await _workspaces(db)
    collaborator = await user_named(db, f"gate-collaborator-{uuid.uuid4().hex[:6]}")
    admin = await _admin(db)
    for user in (collaborator, admin):
        db.add(SessionCollaborator(session_id=sessions["private"], user_id=user.id, role="observer",
                                   invited_by=owner.id))
    await db.commit()
    canvas_manager.get_or_create(sessions["private"])
    for user in (collaborator, admin):
        for route in SESSION_CONTENT_READS:
            response = await client.get(route.format(id=sessions["private"]), headers=bearer(user.id))
            assert response.status_code == 200, (route, response.text[:300])


async def test_the_session_content_routes_exist():
    from fastapi.routing import APIRoute

    from app.main import app
    from app.web._helpers.private_workspace_gate import SESSION_CONTENT_ROUTES

    served = {(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods}
    assert SESSION_CONTENT_ROUTES <= served, SESSION_CONTENT_ROUTES - served


async def test_a_platform_admin_still_reaches_a_shared_workspace(client, db):
    _owner, workspaces, _sessions = await _workspaces(db)
    headers = (await _outsiders(db))["platform admin"]
    response = await client.get(f"/admin/chat/api/panel/projects/{workspaces['shared']}/config", headers=headers)
    assert response.status_code == 200, response.text[:300]


async def test_the_own_session_and_shell_routes_exist():
    from fastapi.routing import APIRoute

    from app.main import app
    from app.web._helpers.private_workspace_gate import CHAT_SHELL_ROUTES, OWN_SESSION_ROUTES

    assert OWN_SESSION_ROUTES | CHAT_SHELL_ROUTES <= {route.path for route in app.routes if isinstance(route, APIRoute)}


async def test_an_admin_following_a_stale_or_foreign_chat_link_gets_the_shell(client, db):
    _owner, _named, sessions = await _workspaces(db)
    headers = (await _outsiders(db))["platform admin"]
    answers = {}
    for kind, session_id in sessions.items():
        shell = await client.get(f"/chat?session_id={session_id}", headers=headers)
        redirect = await client.get(f"/admin/chat?session_id={session_id}", headers=headers)
        assert redirect.headers["location"] == f"/chat?session_id={session_id}", redirect.text[:300]
        answers[kind] = (_answer(shell, session_id), redirect.status_code)
    assert answers["private"][0][0] == 200 and answers["private"][1] == 307, answers
    assert answers["private"] == answers["unknown"], answers


SESSION_REFUSALS = (
    ("GET", "/api/v1/sessions/{id}", None),
    ("POST", "/api/v1/sessions/{id}/messages", {"content": "hello"}),
    ("POST", "/api/v1/sessions/{id}/messages/" + str(uuid.uuid4()) + "/feedback", {"rating": "good"}),
    ("POST", "/chat/api/sessions/{id}/rename", {"title": "renamed"}),
)


async def test_a_refused_session_answers_an_admin_with_the_routes_own_missing_session_body(client, db):
    _owner, _named, sessions = await _workspaces(db)
    callers = await _outsiders(db)
    for method, route, body in SESSION_REFUSALS:
        admin = await _answers(client, route, sessions, callers["platform admin"], method, body)
        member = await _answers(client, route, {"unknown": sessions["unknown"]}, callers["outsider"], method, body)
        assert admin["private"] == admin["unknown"] == member["unknown"], (route, admin, member)
        assert admin["private"][0] == 404 and "Session not found" in admin["private"][1], (route, admin)
