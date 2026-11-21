"""Every route that takes a Workspace id, in any request shape (path, query, form field, body-model field at any
depth, plain dict body key, or a key a dependency reads from the request itself), resolves it before anything is
written or sent: on a write an id that names no Workspace is 404 ``project_not_found`` for every caller (a platform
admin included), and on every route, reads included, an outsider (an ordinary member, a non-admin Work operator and a
delegated admin-panel permission holder of another Workspace) naming a shared foreign Workspace or somebody else's private one gets exactly the answer of an
unknown id, so an outsider never learns whether a Workspace exists and never reads or changes its data.

"Nothing is written" is the content of every table (an in-place update counts), the process-wide speaker profiles,
and no outbound HTTP request or subprocess start (``workspace_id_route_inventory``). The routes are read from the
running application, so a new route is covered without being listed here. Each request is the smallest the route
accepts; the Workspace check comes before any other business validation, so it answers first. A route whose path
addresses a resource (the Workspace, or another id the sweep can only fill with an unknown value) answers its own 404
wording. One request slot at a time and real related resources: ``test_workspace_id_route_slots``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.routing import APIRoute

from app.main import app
from tests.workspace_id_route_inventory import (
    NOT_A_BODY_KEY,
    build_request,
    changed,
    record_side_effects,
    refuses_an_unknown_workspace,
    snapshot,
    workspace_routes,
)
from tests.workspace_id_route_support import (  # noqa: F401 - the autouse fixtures, active by import
    _fixtures_on,
    _platform_configured,
    compare_answers,
    foreign_workspaces,
    personas_of,
    refusal_code,
)

pytestmark = pytest.mark.asyncio

# A run start (a workflow run and every DAG flow start) answers its own typed contract for a Workspace that does not
# exist (``needs_configuration`` / ``workspace_required``, 409); a chat turn its turn refusal (``project_not_found``,
# 404). Every other route answers 404 ``project_not_found``.
RUN_START = {"/api/v1/workflow-runs", "/api/v1/flows/versions/{version_id}/run",
             "/api/v1/flows/versions/{version_id}/partial-run", "/api/v1/flows/capabilities/{tool_name}/run"}
CHAT_TURN = {"/chat/api/send", "/admin/chat/api/send"}
# The Teams call proxy's callback is authenticated by the call's token, not by a user: without it the answer is 401
# before the Workspace is read; with it, an unknown Workspace is 404 (``test_an_authenticated_call_callback...``).
WEBHOOK = {"/api/v1/teams/calls/incoming-call": (401, "channel_webhook_unauthenticated")}

ROUTES = workspace_routes()
IDS = [f"{case.method} {case.path} [{','.join(sorted(case.shapes))}]" for case in ROUTES]
REFUSING = [case for case in ROUTES if refuses_an_unknown_workspace(case)]
REFUSING_IDS = [f"{case.method} {case.path} [{','.join(sorted(case.shapes))}]" for case in REFUSING]


async def test_the_sweep_finds_the_workspace_routes_in_every_request_shape():
    by_shape = {shape: {case.path for case in ROUTES if shape in case.shapes}
                for shape in ("path", "query", "form", "model", "dict")}
    assert len(REFUSING) >= 200 and len(ROUTES) >= 400, (len(REFUSING), len(ROUTES))
    assert {"/api/v1/sessions", "/admin/chat/api/panel/scenarios", "/admin/chat/api/panel/webhooks"} <= by_shape["model"]
    assert {"/admin/tools/configs/save", "/api/v1/speakers/enroll", "/api/v1/speakers/remove"} <= by_shape["form"]
    assert {"/api/v1/admin/operations/emergency-stop", "/api/v1/admin/operations/emergency-stop/resume",
            "/api/v1/admin/code-graph/backfill", "/api/v1/flows/versions/{version_id}/run",
            "/api/v1/flows/versions/{version_id}/partial-run",
            "/api/v1/flows/capabilities/{tool_name}/run"} <= by_shape["dict"]
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


async def test_an_authenticated_call_callback_for_an_unknown_workspace_is_404(client):
    from app.services.teams_calling.audio_ws_token import issue_call_audio_token, revoke_call_audio_token

    token = issue_call_audio_token("call-sweep", channel_id="901")
    try:
        response = await client.post("/api/v1/teams/calls/incoming-call", params={
            "call_id": "call-sweep", "channel_id": "901", "project_id": str(uuid.uuid4()), "audio_token": token})
    finally:
        revoke_call_audio_token("call-sweep")
    assert (response.status_code, refusal_code(response)) == (404, "project_not_found"), response.text


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
    elif case.path in WEBHOOK:
        assert (response.status_code, refusal_code(response)) == WEBHOOK[case.path], response.text[:300]
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
    """An outsider never learns whether a Workspace exists: for an ordinary member, a non-admin Work operator and a
    delegated admin-panel permission holder of another Workspace, a shared foreign Workspace, somebody else's private
    one and an id that names no Workspace get the same status and body, on every route (reads included), and none of
    them reads, writes or sends anything of the foreign Workspace."""
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
