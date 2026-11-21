"""Devices on the Knowledge MCP: a device lists only its granted operations, reads through the same gates without the credentials, waits for a person before a write, and gets nothing outside its Workspace."""

from __future__ import annotations

import json

import pytest

from app.models import Project
from app.services.approval.resolution_service import resolve_approval_request
from app.services.mcp_governed_knowledge import McpCaller
from app.services.mcp_rest_tools import run_rest_mcp_tool
from app.services.rest_connector.definitions import update_operation
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
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


# ── Devices: rest_operations / rest_call on the Knowledge MCP ────────────────


def _caller(user_id: str, workspace_id: str, scopes=("knowledge:read", "knowledge:write")) -> McpCaller:
    return McpCaller(user_id=user_id, grant_id=f"grant-{user_id[:8]}", scopes=tuple(scopes),
                     workspace_header=workspace_id, client_name="claude-code")


@pytest.fixture
async def device(db, api):  # noqa: F811
    """A member of one Workspace (platform role ``viewer``), granted there; another Workspace has its own grant."""
    workspace = await seed_workspace(db)
    other = await seed_workspace(db)
    member = await seed_member(db, workspace_id=workspace, role="member")
    definition, operations = await _setup(db, grants=[{"role": "viewer", "workspace_id": workspace,
                                                       "body_scope": {"assignment_group": "G1"}}])
    # An operation only another Workspace's people may use stays invisible here.
    await update_operation(db, definition["id"], operations["update_ticket"]["id"], {
        "grants": [{"role": "viewer", "workspace_id": other}]})
    await db.commit()
    return member, workspace


async def _mcp(db, caller, tool: str, arguments: dict) -> dict:
    result = await run_rest_mcp_tool(db, caller=caller, tool_name=tool, arguments=arguments)
    await db.commit()
    return result


@pytest.mark.asyncio
async def test_a_device_lists_only_what_it_is_granted_in_its_workspace(db, device):
    member, workspace = device

    listed = await _mcp(db, _caller(member, workspace), "rest_operations", {})

    by_name = {entry["operation"]: entry for entry in listed["operations"]}
    assert set(by_name) == {LIST, CREATE}, listed
    assert by_name[CREATE]["class"] == "write" and by_name[LIST]["class"] == "read"
    assert "title" in by_name[CREATE]["parameters"]["properties"]["body"]["properties"]
    assert (await _mcp(db, _caller(member, workspace), "rest_operations", {"query": "list"}))["count"] == 1


@pytest.mark.asyncio
async def test_a_device_reads_through_the_same_gates_and_never_sees_the_credentials(db, api, device):  # noqa: F811
    member, workspace = device

    result = await _mcp(db, _caller(member, workspace), "rest_call", {"operation": LIST, "arguments": {}})
    foreign = await _mcp(db, _caller(member, workspace), "rest_call", {"operation": UPDATE,
                                                                       "arguments": {"id": "1", "body": {}}})

    assert result["status_code"] == 200, result
    assert api.requests[0].headers["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in json.dumps(result, default=str)
    assert foreign["reason"] == "rest_operation_unknown" and len(api.requests) == 1
    runs = await _runs(db)
    assert runs[0].actor_user_id == member and runs[0].project_id == workspace


@pytest.mark.asyncio
async def test_a_device_write_waits_for_a_person_in_octryx_then_the_same_call_runs_once(db, api, device, no_policy):  # noqa: F811
    api.answer = _created
    member, workspace = device
    call = {"operation": CREATE, "arguments": {"body": {"title": "From my laptop"}}}

    read_only_grant = await _mcp(db, _caller(member, workspace, scopes=("knowledge:read",)), "rest_call", call)
    held = await _mcp(db, _caller(member, workspace), "rest_call", call)

    assert read_only_grant["state"] == "denied" and api.requests == []
    assert held["approval_required"] is True and held["approval_id"] and api.requests == [], held
    preview = await _preview(db, held["change_preview_id"])
    assert preview["rule"] == "device_external_write" and preview["subtitle"].startswith("A device asks to write to")
    assert f"request: POST {API}/tickets" in preview["details"]

    admin = await _admin(db)
    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=admin.id, status="approved")
    await db.commit()
    done = await _mcp(db, _caller(member, workspace), "rest_call", call)
    again = await _mcp(db, _caller(member, workspace), "rest_call", call)

    assert done["status_code"] == 201, done
    assert json.loads(api.requests[0].content)["assignment_group"] == "G1"
    assert again["approval_required"] is True and len(api.requests) == 1
    assert (await _runs(db))[0].approval_id == held["approval_id"]


@pytest.mark.asyncio
async def test_a_device_outside_the_workspace_gets_nothing(db, device):
    member, _workspace = device
    stranger_workspace = await seed_workspace(db)
    (await db.get(Project, stranger_workspace)).config = {}
    await db.commit()

    listed = await _mcp(db, _caller(member, stranger_workspace), "rest_operations", {})

    assert "operations" not in listed and listed.get("state") in {"not_found", "denied"}, listed
