"""Custom REST connector: the executor against recorded answers behind the real pinned egress transport.

Octryx is the authorization layer: the API is reached with a technical account, so these tests
prove what the person may and may not get through it: grants per role, the injected data scope the model cannot
override, the result filter, the fixed host, and that no secret reaches a result or the audit row. Writes
are covered in ``test_rest_connector_writes``.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.services.dynamic_tool_definitions import list_runtime_dynamic_tool_definitions
from app.services.rest_connector.executor import execute_rest_tool
from app.tools.capability_requirements import tool_required_capability
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.rest_connector_executor_support import LIST_TOOL, _admin, _context, _runs, _setup, api  # noqa: F401
from tests.rest_connector_support import SECRET

pytestmark = pytest.mark.usefixtures("public_source_dns")


def _no_secret_anywhere(result, runs, secret=SECRET):
    assert secret not in json.dumps(result, default=str)
    for run in runs:
        assert secret not in json.dumps([run.error, run.arguments_json, run.scope_json], default=str)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auth", "secrets", "expect"),
    [
        ({"scheme": "api_key_header", "header_name": "X-Key"}, {"api_key": SECRET}, ("header", "X-Key", SECRET)),
        ({"scheme": "api_key_query", "query_name": "key"}, {"api_key": SECRET}, ("query", "key", SECRET)),
        ({"scheme": "bearer"}, {"token": SECRET}, ("header", "Authorization", f"Bearer {SECRET}")),
        ({"scheme": "basic"}, {"username": "svc", "password": SECRET},
         ("header", "Authorization", "Basic " + base64.b64encode(f"svc:{SECRET}".encode()).decode())),
    ],
)
async def test_each_scheme_authenticates_and_no_secret_reaches_result_or_audit(db, api, auth, secrets, expect):  # noqa: F811
    await _setup(db, auth=auth, secrets=secrets)
    admin = await _admin(db)

    result = await execute_rest_tool(LIST_TOOL, {}, _context(db, admin.id))

    assert result["status_code"] == 200, result
    sent = api.requests[0]
    where, name, value = expect
    assert (sent.headers.get(name) if where == "header" else sent.url.params.get(name)) == value
    _no_secret_anywhere(result, await _runs(db))


@pytest.mark.asyncio
async def test_oauth2_client_credentials_token_is_fetched_once_and_cached(db, api):  # noqa: F811
    def answer(request):
        if request.url.path == "/token":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        return httpx.Response(200, json={"items": []})

    api.answer = answer
    await _setup(db, auth={"scheme": "oauth2_client_credentials", "token_url": "https://auth.example.test/token"},
                 secrets={"client_id": "svc", "client_secret": SECRET})
    admin = await _admin(db)

    for _ in range(2):
        result = await execute_rest_tool(LIST_TOOL, {}, _context(db, admin.id))
        assert result["status_code"] == 200, result

    token_calls = [request for request in api.requests if request.url.path == "/token"]
    api_calls = [request for request in api.requests if request.url.path == "/v1/tickets"]
    assert len(token_calls) == 1
    assert all(request.headers["authorization"] == "Bearer at-1" for request in api_calls)
    _no_secret_anywhere(result, await _runs(db))


@pytest.mark.asyncio
async def test_missing_secret_is_refused_without_a_request(db, api):  # noqa: F811
    await _setup(db, auth={"scheme": "bearer"}, secrets={})
    admin = await _admin(db)

    result = await execute_rest_tool(LIST_TOOL, {}, _context(db, admin.id))

    assert result["code"] == "auth_config" and "token" in result["error"]
    assert api.requests == []


@pytest.mark.asyncio
async def test_scope_is_injected_the_model_cannot_override_it_and_out_of_scope_rows_are_dropped(db, api):  # noqa: F811
    api.answer = lambda request: httpx.Response(200, json={"items": [
        {"number": 1, "assignment_group": "G1"}, {"number": 2, "assignment_group": "G2"}]})
    await _setup(db)
    admin = await _admin(db)

    result = await execute_rest_tool(LIST_TOOL, {"state": "open"}, _context(db, admin.id))

    assert api.requests[0].url.params["assignment_group"] == "G1"
    assert result["data"]["items"] == [{"number": 1, "assignment_group": "G1"}]
    assert result["dropped_out_of_scope"] == 1

    refused = await execute_rest_tool(LIST_TOOL, {"assignment_group": "G2"}, _context(db, admin.id))

    assert refused["code"] == "scope_violation"
    assert len(api.requests) == 1  # nothing sent for the contradicting call
    runs = await _runs(db)
    assert runs[0].identity == "technical"
    assert runs[0].scope_json["params"] == {"assignment_group": "G1"}
    assert runs[0].dropped_count == 1 and runs[0].status == "succeeded"
    assert runs[1].status == "refused" and runs[1].failure_category == "scope_violation"
    # The refusal's audit names what was asked and what the grants allow (not an empty scope).
    assert runs[1].scope_json["requested"] == {"assignment_group": "G2"}
    assert runs[1].scope_json["allowed"][0]["params"] == {"assignment_group": "G1"}


@pytest.mark.asyncio
async def test_a_role_without_grant_is_refused_and_not_offered(db, api):  # noqa: F811
    await _setup(db)
    admin = await _admin(db)
    viewer = _context(db, admin.id, roles=("viewer",))

    result = await execute_rest_tool(LIST_TOOL, {}, viewer)

    assert result["code"] == "not_granted"
    assert api.requests == []
    names = {item["function"]["name"] for item in await list_runtime_dynamic_tool_definitions(db, viewer)}
    assert not any(name.startswith("rest__") for name in names)


@pytest.mark.asyncio
async def test_a_write_operation_is_offered_as_a_write_that_needs_deliver(db, api):  # noqa: F811
    """Phase 2: a write is offered like a read, but its metadata says it writes, so every gate treats it as one."""
    await _setup(db, grants=[{"role": "agent"}], enable=("list_tickets", "close_ticket"))
    admin = await _admin(db)
    context = _context(db, admin.id)

    offered = {item["function"]["name"]: item["function"] for item in
               await list_runtime_dynamic_tool_definitions(db, context)}

    assert LIST_TOOL in offered and "rest__tickets__close_ticket" in offered
    assert "changes data" in offered["rest__tickets__close_ticket"]["description"]
    assert tool_required_capability("rest__tickets__close_ticket") == "deliver"
    assert tool_required_capability(LIST_TOOL) == "read_only"
