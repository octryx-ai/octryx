"""The session MCP endpoint: a basic set with tool_search and tool_call, a found tool listed from the next tools/list
on, the Workspace policy and membership on search and call, and a write approved in Octryx before it runs."""

from __future__ import annotations

import json
import uuid

from app.models import Project
from app.services.approval.resolution_service import resolve_approval_request
from app.services.mcp_session_surface import BASIC_TOOLS
from app.tools.registry import TOOL_REGISTRY
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.mcp_claude_code_parity_support import SCOPES, _gateway_session, _native
from tests.mcp_native_support import mcp_request, native_token


async def _world(db, monkeypatch, *, denied: tuple[str, ...] = ()):
    _native(db, monkeypatch)
    workspace = await seed_workspace(db)
    member = await seed_member(db, workspace_id=workspace, role="member")
    if denied:
        project = await db.get(Project, workspace)
        project.config = {**(project.config or {}), "tool_policy": {"denylist": list(denied)}}
    session_key = str(uuid.uuid4())
    await _gateway_session(db, member, workspace, session_key)
    await db.commit()
    token = await native_token(db, user_id=member, scopes=list(SCOPES))
    return token, {"X-Octryx-Workspace": workspace, "X-Octryx-Session": session_key}, member


async def _listed(token, headers) -> set[str]:
    return {tool["name"] for tool in (await mcp_request(token, "tools/list", headers=headers))["result"]["tools"]}


async def _call(token, headers, name, arguments) -> tuple[dict, bool]:
    result = (await mcp_request(token, "tools/call", {"name": name, "arguments": arguments}, headers))["result"]
    return json.loads(result["content"][0]["text"]), bool(result.get("isError"))


async def test_a_session_lists_its_basic_set_and_finds_and_calls_every_other_tool(db, monkeypatch):
    token, headers, _member = await _world(db, monkeypatch)

    listed = await _listed(token, headers)
    assert {"tool_search", "tool_call", "workflow_run_status", "knowledge_search"} <= listed
    assert listed <= {*BASIC_TOOLS, "tool_search", "tool_call"}
    assert "product_run_list" not in listed

    found, _ = await _call(token, headers, "tool_search", {"query": "select:product_run_list"})
    assert [tool["name"] for tool in found["tools"]] == ["product_run_list"]
    assert found["tools"][0]["input_schema"]["type"] == "object"
    runs, failed = await _call(token, headers, "tool_call", {"name": "product_run_list", "arguments": {}})
    assert not failed and "workflow_runs" in runs, runs

    # Loaded for this gateway session: listed from its next tools/list on, and callable by its own name.
    assert "product_run_list" in await _listed(token, headers)
    direct, failed = await _call(token, headers, "product_run_list", {})
    assert not failed and direct == runs


async def test_a_tool_the_workspace_policy_hides_is_neither_found_nor_called(db, monkeypatch):
    token, headers, _member = await _world(db, monkeypatch, denied=("product_run_list",))

    found, _ = await _call(token, headers, "tool_search", {"query": "select:product_run_list"})
    assert "product_run_list" not in {tool["name"] for tool in found["tools"]}
    for name, arguments in (("tool_call", {"name": "product_run_list"}), ("product_run_list", {})):
        refused, _ = await _call(token, headers, name, arguments)
        assert refused["reason"] == "tool_not_offered", refused
    other, failed = await _call(token, {**headers, "X-Octryx-Workspace": str(uuid.uuid4())}, "tool_search",
                                {"query": "workflow"})
    assert other["state"] == "not_found"


async def test_the_tools_r3b_moved_off_hand_written_registration_are_found_by_tool_search(db, monkeypatch):
    token, headers, _member = await _world(db, monkeypatch)
    moved = ("knowledge_changes", "memory_remember", "graph_neighbors", "create_diagram", "web_search")

    found, _ = await _call(token, headers, "tool_search", {"query": "select:" + ",".join(moved)})
    assert {tool["name"] for tool in found["tools"]} == set(moved)


async def test_a_moved_tool_the_workspace_policy_hides_stays_unreachable_with_knowledge_write(db, monkeypatch):
    # Hand-written until R3b with their own registration; the registry's visibility decides them now.
    assert "knowledge:write" in SCOPES
    token, headers, _member = await _world(db, monkeypatch, denied=("memory_remember", "knowledge_read"))

    assert not {"memory_remember", "knowledge_read"} & await _listed(token, headers)
    for name in ("memory_remember", "knowledge_read"):
        found, _ = await _call(token, headers, "tool_search", {"query": f"select:{name}"})
        assert name not in {tool["name"] for tool in found["tools"]}
        for called, arguments in (("tool_call", {"name": name, "arguments": {"text": "x"}}), (name, {"text": "x"})):
            refused, _ = await _call(token, headers, called, arguments)
            assert refused["reason"] == "tool_not_offered", refused


async def test_a_write_waits_for_a_persons_approval_in_octryx_then_the_repeat_runs(db, monkeypatch):
    token, headers, member = await _world(db, monkeypatch)
    ran: list[dict] = []

    async def execute(params, context):
        ran.append(dict(params))
        return {"state": "recorded", "summary": params.get("summary")}

    monkeypatch.setattr(TOOL_REGISTRY["knowledge_episode_summary"], "execute", execute)
    call = {"name": "knowledge_episode_summary", "arguments": {"summary": "Shipping fee rule agreed."}}

    held, failed = await _call(token, headers, "tool_call", call)
    assert failed and held["approval_required"] is True and held["approval_id"], held
    assert ran == [], "nothing runs before the approval"
    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=member, status="approved")
    await db.commit()

    done, failed = await _call(token, headers, "tool_call", call)
    assert not failed and done == {"state": "recorded", "summary": "Shipping fee rule agreed."}, done
    assert len(ran) == 1
