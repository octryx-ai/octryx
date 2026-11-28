"""Custom REST connector: the executor against recorded answers behind the real pinned egress transport."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.services.rest_connector.executor import execute_rest_tool
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.services.rest_connector.rest_connector_executor_support import (  # noqa: F401
    LIST_TOOL,
    _admin,
    _context,
    _runs,
    _setup,
    api,
)
from tests.support.rest_connector_support import SECRET

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
    assert len(api.requests) == 1
    runs = await _runs(db)
    assert runs[0].identity == "technical"
    assert runs[0].scope_json["params"] == {"assignment_group": "G1"}
    assert runs[0].dropped_count == 1 and runs[0].status == "succeeded"
    assert runs[1].status == "refused" and runs[1].failure_category == "scope_violation"
    assert runs[1].scope_json["requested"] == {"assignment_group": "G2"}
    assert runs[1].scope_json["allowed"][0]["params"] == {"assignment_group": "G1"}




