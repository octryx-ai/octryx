"""Every route that takes a Workspace id resolves it before anything is written or sent, and an outsider gets
exactly the answer of an unknown id, so never learns whether a Workspace exists."""

from __future__ import annotations

import uuid

import pytest
from fastapi.routing import APIRoute

from app.main import app
from tests.policy_engine_support import bearer
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workspace_id_route_inventory import (
    NOT_A_BODY_KEY,
    build_request,
    changed,
    record_side_effects,
    refuses_an_unknown_workspace,
    request_slots,
    snapshot,
    workspace_routes,
)
from tests.workspace_id_route_support import (  # noqa: F401 - the autouse fixtures, active by import
    FOREIGN_MARKER,
    _fixtures_on,
    _platform_configured,
    answer_text,
    build_scope_request,
    compare_answers,
    foreign_workspaces,
    personas_of,
    refusal_code,
    scope_routes,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]

# A run start (a workflow run and every DAG flow start) answers its own typed contract for a Workspace that does not
# exist (``needs_configuration`` / ``workspace_required``, 409); a chat turn its turn refusal (``project_not_found``,
# 404). Every other route answers 404 ``project_not_found``.
RUN_START = {"/api/v1/workflow-runs"}
CHAT_TURN = {"/chat/api/send", "/admin/chat/api/send"}

ROUTES = workspace_routes()
IDS = [f"{case.method} {case.path} [{','.join(sorted(case.shapes))}]" for case in ROUTES]
REFUSING = [case for case in ROUTES if refuses_an_unknown_workspace(case)]
REFUSING_IDS = [f"{case.method} {case.path} [{','.join(sorted(case.shapes))}]" for case in REFUSING]


async def test_the_sweep_finds_the_workspace_routes_in_every_request_shape():
    by_shape = {shape: {case.path for case in ROUTES if shape in case.shapes}
                for shape in ("path", "query", "form", "model", "dict")}
    assert len(REFUSING) >= 200 and len(ROUTES) >= 400, (len(REFUSING), len(ROUTES))
    assert {"/api/v1/sessions", "/admin/chat/api/panel/webhooks"} <= by_shape["model"]
    assert {"/admin/tools/configs/save", "/api/v1/speakers/enroll", "/api/v1/speakers/remove"} <= by_shape["form"]
    assert {"/api/v1/admin/operations/emergency-stop", "/api/v1/admin/operations/emergency-stop/resume",
            "/api/v1/admin/code-graph/backfill"} <= by_shape["dict"]
    assert "/admin/chat/api/panel/runtime-settings" in by_shape["query"]
    assert "/api/v1/workspaces/{workspace_id}/web-search/mode" in by_shape["path"]
    assert "/api/v1/workspaces/{workspace_id}/knowledge/bindings" in by_shape["model"]  # source_workspace_id
    assert "/admin/chat/api/panel/channel-delivery-targets" in by_shape["dict"]  # read by the service it calls
    # read by the Secure Work scope dependency from the request itself, not a declared parameter
    assert "/api/v1/secure-work/work-items" in by_shape["query"]
    assert {"/api/v1/connector-watchers", "/api/v1/connector-watchers/rules", "/api/v1/work-roles/functions",
            "/api/v1/work-roles/roles", "/api/v1/feature-flags/{key}"} <= by_shape["query"]
    routes = {(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods}
    assert set(NOT_A_BODY_KEY) <= routes, set(NOT_A_BODY_KEY) - routes  # no stale exemption


@pytest.mark.parametrize("case", REFUSING, ids=REFUSING_IDS)
async def test_an_unknown_workspace_is_refused_for_an_admin_and_nothing_is_written_or_sent(client, db, auth_headers,
                                                                                             monkeypatch, case):
    from tests.phased_workflow_fixtures import admin_user

    request = build_request(case, str(uuid.uuid4()), (await admin_user(db)).id)
    before = await snapshot(db)
    effects = record_side_effects(monkeypatch)
    response = await client.request(case.method, headers=auth_headers, **request)
    label = f"{case.method} {case.path}"
    if case.path in CHAT_TURN:  # the chat API answers a turn refusal with its sentence
        assert response.status_code == 404 and "does not exist" in response.text, response.text[:300]
    elif case.addresses_a_resource and case.path not in RUN_START:  # an unknown resource: its own 404 wording
        assert response.status_code == 404, f"{label}: {response.text[:300]}"
    else:
        expected = (409, "workspace_required") if case.path in RUN_START else (404, "project_not_found")
        assert (response.status_code, refusal_code(response)) == expected, f"{label}: {response.text[:300]}"
    db.expire_all()
    assert changed(before, await snapshot(db)) == [], label
    assert effects.calls == [], label


# The routes a delegated admin-panel permission opens for every shared Workspace without membership (``projects``
# read/write: a Workspace's access assignments): a shared Workspace is the delegated admin's to administer there, so
# only somebody else's private Workspace must answer like an unknown id (the route refuses it itself).
DELEGATED_WITHOUT_MEMBERSHIP = {(method, f"{mount}/chat/api/panel/projects/{{project_id}}/access")
                                for method in ("GET", "PUT") for mount in ("", "/admin")}


@pytest.mark.parametrize("case", ROUTES, ids=IDS)
async def test_a_foreign_workspace_answers_an_outsider_exactly_like_an_unknown_one(client, db, case):
    (_mine, personas), foreign = await personas_of(db, "member"), await foreign_workspaces(db)
    await db.commit()
    for persona, caller in personas.items():
        label = f"{case.method} {case.path} as {persona}"
        named = {**foreign, "unknown": str(uuid.uuid4())}
        if persona == "delegated" and (case.method, case.path) in DELEGATED_WITHOUT_MEMBERSHIP:
            named.pop("shared")
        answers = await compare_answers(client, db, case, caller, named, label)
        if "shared" in answers:
            assert answers["shared"] == answers["unknown"], f"{label}: shared {answers['shared']} != {answers['unknown']}"
        assert answers["private"] == answers["unknown"], f"{label}: private {answers['private']} != {answers['unknown']}"


@pytest.mark.parametrize("case", ROUTES, ids=IDS)
async def test_a_private_workspace_answers_an_anonymous_caller_and_a_platform_admin_like_an_unknown_one(client, db,
                                                                                                         case):
    from app.middleware.audit.request_audit import _ensure_anonymous_audit_user
    from tests.phased_workflow_fixtures import admin_user

    foreign, admin_id = await foreign_workspaces(db), (await admin_user(db)).id
    await _ensure_anonymous_audit_user(db)  # the request audit's first anonymous request creates it once per platform
    await db.commit()
    label = f"{case.method} {case.path}"
    anonymous = await compare_answers(client, db, case, None, {**foreign, "unknown": str(uuid.uuid4())},
                                      f"{label} anonymous")
    assert anonymous["private"] == anonymous["shared"] == anonymous["unknown"], f"{label} anonymous: {anonymous}"
    if not {"path", "query"} & case.shapes:  # the gate reads the path and query; a body's Workspace is the route's
        return
    answers = await compare_answers(client, db, case, admin_id, {"private": foreign["private"],
                                                                 "unknown": str(uuid.uuid4())}, f"{label} admin")
    assert answers["private"] == answers["unknown"], f"{label} admin: {answers}"


BODY_SLOTS = [(case, slot) for case in ROUTES for slot in request_slots(case) if slot[0] in ("body", "form")]


@pytest.mark.parametrize(("case", "slot"), BODY_SLOTS,
                         ids=[f"{case.method} {case.path} [{':'.join(slot)}]" for case, slot in BODY_SLOTS])
async def test_a_private_workspace_in_one_body_slot_answers_a_platform_admin_like_an_unknown_one(client, db, case,
                                                                                                  slot):
    from tests.phased_workflow_fixtures import admin_user

    foreign, admin_id = await foreign_workspaces(db), (await admin_user(db)).id
    await db.commit()
    label = f"{case.method} {case.path} [{':'.join(slot)}] admin"
    answers = await compare_answers(client, db, case, admin_id, {"private": foreign["private"],
                                                                 "unknown": str(uuid.uuid4())}, label,
                                    own_workspace_id=foreign["shared"], varied=slot)
    assert answers["private"] == answers["unknown"], f"{label}: {answers}"


SCOPED = [(case, scope_type) for case in scope_routes() for scope_type in case.scope_types]


async def test_the_sweep_finds_the_routes_whose_scope_names_a_workspace():
    found = {(case.method, case.path, case.location) for case, _scope_type in SCOPED}
    panel = "/admin/chat/api/panel/engineering-knowledge"
    assert {("POST", f"{panel}/graph/nodes", "body"), ("GET", f"{panel}/graph/nodes", "query"),
            ("POST", f"{panel}/graph/edges", "body"), ("POST", f"{panel}/versions/{{version_id}}/assignments", "body"),
            ("GET", f"{panel}/graph/entities/{{entity_ref}}", "query"),
            ("POST", "/api/v1/data/exports", "body")} <= found, found


@pytest.mark.parametrize(("case", "scope_type"), SCOPED,
                         ids=[f"{case.method} {case.path} [{case.location}:{scope_type}]" for case, scope_type in SCOPED])
async def test_a_private_workspace_named_by_a_scope_answers_a_platform_admin_like_an_unknown_one(client, db, case,
                                                                                                 scope_type):
    from tests.phased_workflow_fixtures import admin_user

    foreign, admin_id = await foreign_workspaces(db), (await admin_user(db)).id
    await db.commit()
    label = f"{case.method} {case.path} [{case.location}:{scope_type}] admin"
    before, answers = await snapshot(db), {}
    for kind, workspace_id in (("private", foreign["private"]), ("unknown", str(uuid.uuid4()))):
        with pytest.MonkeyPatch.context() as patch:
            effects = record_side_effects(patch)
            response = await client.request(case.method, headers=bearer(admin_id),
                                            **build_scope_request(case, scope_type, workspace_id))
        assert effects.calls == [], f"{label} sent for the {kind} Workspace: {effects.calls}"
        assert FOREIGN_MARKER not in response.text, f"{label} disclosed the {kind} Workspace: {response.text[:300]}"
        answers[kind] = (response.status_code, refusal_code(response), answer_text(response, workspace_id))
    db.expire_all()
    assert changed(before, await snapshot(db)) == [], label
    assert answers["private"] == answers["unknown"], f"{label}: {answers}"
    if answers["unknown"][:2] == (404, "project_not_found"):  # the scope check refused it: a visible one gets past
        response = await client.request(case.method, headers=bearer(admin_id),
                                        **build_scope_request(case, scope_type, foreign["shared"]))
        assert refusal_code(response) != "project_not_found", f"{label} shared: {response.text[:300]}"
    else:  # a read filters by the scope instead
        assert case.method == "GET" and answers["unknown"][0] == 200, f"{label}: {answers}"
