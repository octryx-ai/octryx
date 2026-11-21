"""Custom REST connector: writes through the gates the platform already has, and devices over MCP.

A write reaches another system with a technical account, so these tests prove who decides it: the run's class (a
read-only run never writes, ``deliver`` unless the admin said ``change``), the chat's one write plan per request, the
central approval gate with a preview of the exact request (no credential, secret-looking values masked), a person for
every write of an unattended run or a device, the grant's body scope the model cannot change, no second send of a
write that may not be repeated, and the audit row naming what admitted the write.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from app.models import Session as AgentSession
from app.services.approval.resolution_service import resolve_approval_request
from app.services.rest_connector.definitions import admin_test_call, get_definition, recent_calls, update_operation
from app.services.rest_connector.executor import execute_rest_tool
from app.services.tool_approval_gate import enforce_tool_approval
from app.services.tool_approval_write_kinds import unattended_external_write
from app.tools.capability_requirements import tool_required_capability
from app.tools.context import ToolContext
from app.tools.definitions.rest_tool_classes import forget_rest_tools
from app.tools.registry import execute_tool, execute_tool_with_plugins
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.rest_connector_support import API, SECRET
from tests.rest_connector_writes_support import (  # noqa: F401
    CREATE,
    LIST,
    UPDATE,
    _admin,
    _created,
    _preview,
    _runs,
    _setup,
    api,
    fresh_view,
    no_policy,
)

pytestmark = pytest.mark.usefixtures("public_source_dns")


DELIVER_RUN = {"class": "deliver", "enforced": True, "source": "flow_definition"}


CHAT_STATE = {"class": "read_only", "enforced": True, "source": "chat_default", "escalation_decision": None,
              "chat_connector_writes": True}


TOKEN_IN_BODY = ("sk-li" + "ve0123456789abcdef")


async def _session(db, user_id: str, *, metadata=None) -> AgentSession:
    session = AgentSession(user_id=user_id, agent_type="chat", status="active", metadata_=metadata or {})
    db.add(session)
    await db.flush()
    return session


def _context(db, user_id: str, session_id: str, run_capability=None, project_config=None) -> ToolContext:
    return ToolContext(user_id=user_id, project_ids=[], roles=["agent"], session_id=session_id,
                       project_config=project_config or {}, db=db, run_capability=run_capability)


@pytest.mark.asyncio
async def test_the_grants_body_scope_is_set_last_and_a_body_naming_another_value_is_refused(db, api):  # noqa: F811
    api.answer = _created
    await _setup(db)
    admin = await _admin(db)
    context = _context(db, admin.id, "s-1")

    result = await execute_rest_tool(CREATE, {"body": {"title": "Printer"}}, context)
    refused = await execute_rest_tool(CREATE, {"body": {"title": "x", "assignment_group": "G2"}}, context)

    assert result["status_code"] == 201 and result["writes"] is True, result
    assert json.loads(api.requests[0].content) == {"title": "Printer", "assignment_group": "G1"}
    assert refused["code"] == "scope_violation" and len(api.requests) == 1
    runs = await _runs(db)
    assert runs[0].scope_json["body"] == {"assignment_group": "G1"} and runs[1].status == "refused"


@pytest.mark.asyncio
async def test_a_post_is_never_sent_twice_and_a_put_only_when_its_admin_marked_it_idempotent(db, api):  # noqa: F811
    def flaky():
        answers = iter([httpx.Response(503), httpx.Response(200, json={})])
        return lambda request: next(answers)

    definition, operations = await _setup(db)
    admin = await _admin(db)
    context = _context(db, admin.id, "s-1")

    api.answer = flaky()
    assert (await execute_rest_tool(CREATE, {"body": {"title": "a"}}, context))["code"] == "http_error"
    api.answer = flaky()
    assert (await execute_rest_tool(UPDATE, {"id": "7", "body": {}}, context))["code"] == "http_error"
    assert len(api.requests) == 2  # one send each

    await update_operation(db, definition["id"], operations["update_ticket"]["id"], {"idempotent": True})
    api.answer = flaky()
    retried = await execute_rest_tool(UPDATE, {"id": "7", "body": {}}, context)
    assert retried["status_code"] == 200 and retried["retries"] == 1 and len(api.requests) == 4
    with pytest.raises(HTTPException):
        await update_operation(db, definition["id"], operations["create_ticket"]["id"], {"idempotent": True})


@pytest.mark.asyncio
async def test_a_write_runs_only_in_a_run_whose_class_covers_it(db, api, no_policy):  # noqa: F811
    api.answer = _created
    definition, operations = await _setup(db)
    admin = await _admin(db)
    session = await _session(db, admin.id)
    read_only = _context(db, admin.id, session.id, {"class": "read_only", "enforced": True, "source": "flow_definition"})
    change = _context(db, admin.id, session.id, {"class": "change", "enforced": True, "source": "flow_definition"})

    refused = await execute_tool_with_plugins(CREATE, {"body": {"title": "a"}}, read_only)
    assert refused["capability_refusal"]["required_capability"] == "deliver", refused
    assert (await execute_tool_with_plugins(CREATE, {"body": {"title": "a"}}, change))["capability_refusal"]
    assert api.requests == []

    await update_operation(db, definition["id"], operations["create_ticket"]["id"], {"capability": "change"})
    assert tool_required_capability(CREATE) == "change"
    assert (await execute_tool_with_plugins(CREATE, {"body": {"title": "a"}}, change))["status_code"] == 201

    # A worker whose view is stale (it never listed or dispatched the tool) still cannot write in a read-only run:
    # the executor decides from the stored row.
    forget_rest_tools()
    stale = await execute_rest_tool(CREATE, {"body": {"title": "b"}}, read_only)
    assert stale["code"] == "capability_exceeded" and len(api.requests) == 1


@pytest.mark.asyncio
async def test_a_workflow_write_waits_for_approval_shows_the_request_and_runs_once_with_its_approval_audited(
        db, api, no_policy):  # noqa: F811
    api.answer = _created
    await _setup(db)
    admin = await _admin(db)
    session = await _session(db, admin.id)
    policy = {"approval_policy": {"require_for_risks": ["write"]}}
    context = _context(db, admin.id, session.id, DELIVER_RUN, policy)
    params = {"body": {"title": "Printer", "api_token": TOKEN_IN_BODY}, "X-Request-Source": "octryx"}

    held = await execute_tool_with_plugins(CREATE, params, context)

    assert held["approval_required"] is True and api.requests == [], held
    preview = await _preview(db, held["change_preview_id"])
    shown = json.dumps(preview)
    assert f"request: POST {API}/tickets" in preview["details"] and "connection: Desk prod" in preview["details"]
    assert preview["header_names"] == ["X-Request-Source"] and "octryx" not in shown  # header names only
    assert preview["body"] == {"title": "Printer", "api_token": "[redacted]", "assignment_group": "G1"}
    assert SECRET not in shown and TOKEN_IN_BODY not in shown

    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=admin.id, status="approved")
    done = await execute_tool_with_plugins(CREATE, params, context)
    again = await execute_tool_with_plugins(CREATE, params, context)

    assert done["status_code"] == 201 and done["run"]["approval_id"] == held["approval_id"], done
    assert again["approval_required"] is True and len(api.requests) == 1  # one decision, one write
    assert (await _runs(db))[0].approval_id == held["approval_id"]
    # The admin's audit list names what admitted the write and the chat where it was decided.
    [row] = [row for row in await recent_calls(db) if row["approval_id"]]
    assert row["write"] is True and row["session_id"] == session.id and row["write_plan_id"] is None


@pytest.mark.asyncio
async def test_an_unattended_run_proposes_every_rest_write_even_one_its_admin_declared_change(db, api, no_policy):  # noqa: F811
    definition, operations = await _setup(db)
    await update_operation(db, definition["id"], operations["create_ticket"]["id"], {"capability": "change"})
    admin = await _admin(db)
    session = await _session(db, admin.id)
    scheduled = _context(db, admin.id, session.id, {"class": "deliver", "enforced": True,
                                                   "source": "schedule_definition"})

    assert unattended_external_write(CREATE, scheduled, None) is True
    assert unattended_external_write(LIST, scheduled, None) is False
    held = await execute_tool_with_plugins(CREATE, {"body": {"title": "From an alert"}}, scheduled)
    assert held["approval_required"] is True and api.requests == [], held
    assert await enforce_tool_approval(LIST, {}, scheduled) is None  # reads stay automatic


@pytest.mark.asyncio
async def test_a_chat_write_goes_through_the_one_write_plan_naming_its_connection(db, api):  # noqa: F811
    api.answer = _created
    await _setup(db)
    admin = await _admin(db)
    session = await _session(db, admin.id, metadata={"current_turn_user_message_id": "request-1"})
    chat = _context(db, admin.id, session.id, dict(CHAT_STATE))
    params = {"body": {"title": "Printer on floor 3", "api_token": TOKEN_IN_BODY}}

    asked = await execute_tool_with_plugins(CREATE, params, chat)
    assert asked["code"] == "write_plan_required" and asked["next_tool"] == "propose_write_plan", asked

    held = await execute_tool("propose_write_plan", {"request": "Open a desk ticket",
                                                     "writes": [{"tool": CREATE, "fields": params}]}, chat)
    card = await _preview(db, held["change_preview_id"])
    write = card["writes"][0]
    assert write["tool"] == CREATE and write["connection"] == "Desk prod"
    assert f"request: POST {API}/tickets" in write["details"]
    assert TOKEN_IN_BODY not in json.dumps(card["details"]) and SECRET not in json.dumps(card)
    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=admin.id, status="approved")

    done = await execute_tool_with_plugins(CREATE, params, chat)
    assert done["status_code"] == 201, done
    assert (await _runs(db))[-1].write_plan_id == card["plan_id"]


@pytest.mark.asyncio
async def test_an_admin_test_call_never_writes(db, api):  # noqa: F811
    definition, operations = await _setup(db)
    admin = await _admin(db)

    with pytest.raises(HTTPException) as refused:
        await admin_test_call(db, definition["id"], operations["create_ticket"]["id"], {"arguments": {}},
                              admin_user_id=admin.id)

    assert refused.value.status_code == 400 and api.requests == []


@pytest.mark.asyncio
async def test_the_definition_names_its_scope_bypass_warnings_when_it_loads(db, api):  # noqa: F811
    definition, _operations = await _setup(db, grants=[{"role": "agent", "scope": {"assignment_group": "G1"}}],
                                           enable=("list_tickets",))
    # list_tickets in _setup gets role-only grants; give it the scope without a result filter.
    loaded = await get_definition(db, definition["id"])
    list_op = next(operation for operation in loaded["operations"] if operation["op_key"] == "list_tickets")
    await update_operation(db, definition["id"], list_op["id"], {
        "grants": [{"role": "agent", "scope": {"assignment_group": "G1"}}]})

    loaded = await get_definition(db, definition["id"])
    list_op = next(operation for operation in loaded["operations"] if operation["op_key"] == "list_tickets")

    assert list_op["scope_warnings"] and "state" in list_op["scope_warnings"][0]
    assert any(warning.startswith("'list_tickets': ") for warning in loaded["warnings"])
