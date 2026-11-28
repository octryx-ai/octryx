"""The REST connector executor keeps to its fixed host, does not follow redirects, paginates through a signed cursor that keeps the scope, retries a GET after 429, and is offered and dispatched read-only and audited for the admin test call."""

from __future__ import annotations

import httpx
import pytest

from app.services.rest_connector.definitions import admin_test_call, update_operation
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
from tests.support.rest_connector_support import API

pytestmark = pytest.mark.usefixtures("public_source_dns")


@pytest.mark.asyncio
async def test_arguments_cannot_change_the_host(db, api):  # noqa: F811
    await _setup(db, grants=[{"role": "agent"}], enable=("get_ticket",))
    admin = await _admin(db)

    await execute_rest_tool("rest__tickets__get_ticket", {"id": "https://evil.example.test/x?y=1#"}, _context(db, admin.id))
    await execute_rest_tool("rest__tickets__get_ticket", {"id": "../../admin"}, _context(db, admin.id))

    assert [request.url.host for request in api.requests] == ["api.example.test", "api.example.test"]
    assert api.requests[0].url.raw_path.startswith(b"/v1/tickets/https%3A%2F%2Fevil.example.test")
    assert api.requests[1].url.raw_path == b"/v1/tickets/..%2F..%2Fadmin"


@pytest.mark.asyncio
async def test_a_redirect_to_another_host_is_not_followed(db, api):  # noqa: F811
    api.answer = lambda request: httpx.Response(302, headers={"location": "https://evil.example.test/steal"})
    await _setup(db, grants=[{"role": "agent"}])
    admin = await _admin(db)

    result = await execute_rest_tool(LIST_TOOL, {}, _context(db, admin.id))

    assert result["code"] == "request_failed"
    assert [request.url.host for request in api.requests] == ["api.example.test"]


@pytest.mark.asyncio
async def test_next_url_pagination_round_trips_through_a_signed_cursor_and_keeps_the_scope(db, api):  # noqa: F811
    def answer(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"items": [{"number": 3, "assignment_group": "G1"}], "next": None})
        return httpx.Response(200, json={"items": [{"number": 1, "assignment_group": "G1"}],
                                         "next": f"{API}/tickets?page=2&assignment_group=G2"})

    api.answer = answer
    await _setup(db, pagination={"type": "next_url", "next_path": "next"})
    admin = await _admin(db)

    first = await execute_rest_tool(LIST_TOOL, {}, _context(db, admin.id))
    cursor = first["next_cursor"]
    assert cursor and "http" not in cursor
    second = await execute_rest_tool(LIST_TOOL, {"cursor": cursor}, _context(db, admin.id))

    assert second["data"]["items"] == [{"number": 3, "assignment_group": "G1"}]
    assert second["next_cursor"] is None
    # The API's next link tried another group; the scope value is set again on the followed URL.
    assert api.requests[1].url.params["assignment_group"] == "G1"
    forged_cursor = cursor[:-1] + ("1" if cursor[-1] == "0" else "0")
    forged = await execute_rest_tool(LIST_TOOL, {"cursor": forged_cursor}, _context(db, admin.id))
    assert forged["code"] == "invalid_cursor"
    assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_get_is_retried_after_429_with_retry_after(db, api):  # noqa: F811
    answers = iter([httpx.Response(429, headers={"retry-after": "2"}), httpx.Response(200, json={"items": []})])
    api.answer = lambda request: next(answers)
    await _setup(db, grants=[{"role": "agent"}])
    admin = await _admin(db)

    result = await execute_rest_tool(LIST_TOOL, {}, _context(db, admin.id))

    assert result["status_code"] == 200 and result["retries"] == 1
    assert len(api.requests) == 2 and api.slept == 2.0




@pytest.mark.asyncio
async def test_admin_test_call_uses_the_admins_roles_and_is_audited(db, api):  # noqa: F811
    definition, operations = await _setup(db, enable=())
    admin = await _admin(db)
    # Granted but not enabled: an admin tests an operation before the model is offered it.
    await update_operation(db, definition["id"], operations["list_tickets"]["id"], {"grants": [{"role": "admin"}]})

    result = await admin_test_call(db, definition["id"], operations["list_tickets"]["id"], {"arguments": {}},
                             admin_user_id=admin.id)

    assert result["status_code"] == 200, result
    assert isinstance(result["run"]["duration_ms"], int)
    runs = await _runs(db)
    assert runs[-1].actor_user_id == admin.id and runs[-1].status == "succeeded"

    from app.services.rest_connector.definitions import get_definition, list_definitions, recent_calls

    [listed] = [row for row in await list_definitions(db) if row["id"] == definition["id"]]
    assert listed["operations"] >= 1 and isinstance(listed["connections"], int) and isinstance(listed["warnings"], int)
    [call] = [row for row in await recent_calls(db) if row["id"] == runs[-1].id]
    assert call["user_name"] and "error" in call and "workspace_name" in call
    await update_operation(db, definition["id"], operations["list_tickets"]["id"], {"enabled": True, "grants": []})
    warnings = (await get_definition(db, definition["id"]))["warnings"]
    assert any("enabled without grants" in warning for warning in warnings)
