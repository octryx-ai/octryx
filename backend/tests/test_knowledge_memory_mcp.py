"""The Memory lobe beyond the chat: MCP exposure, automatic capture, tool surfaces.

Contract tests over the real ledger:

- external CLIs reach the same governed tools over the Knowledge MCP; the Workspace is the
  connection's (grant binding or header), never a tool argument, and personal memory stays personal;
- automatic capture at turn end is off by default; when a Workspace enables it, only what the user
  verbatim stated is written, as ``model_inferred`` + ``observed``, secrets are refused, nothing is
  duplicated, and a sub-agent turn is never captured (the governed model is a fake);
- ``memory_recall`` rides with the governed knowledge tools, ``memory_remember`` stays on the
  user-facing chat surface.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.models import AuditLog, Session, ToolCall
from app.models.project.knowledge_memory import KnowledgeMemoryItem
from app.services.mcp_governed_knowledge import McpCaller, run_governed_mcp_tool
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

READ_WRITE = ("knowledge:read", "knowledge:write")


def _caller(user_id: str, **overrides) -> McpCaller:
    values = {
        "user_id": user_id,
        "grant_id": f"grant-{user_id[:8]}",
        "scopes": READ_WRITE,
        "client_name": "claude-code",
    }
    values.update(overrides)
    return McpCaller(**values)


async def _mcp(db, caller: McpCaller, tool_name: str, **arguments):
    return await run_governed_mcp_tool(db, caller=caller, tool_name=tool_name, arguments=arguments)


async def test_mcp_memory_is_scoped_by_the_connection_and_personal_memory_stays_personal(db):
    workspace_id = await seed_workspace(db)
    other_id = await seed_workspace(db)
    owner_id = await seed_member(db, workspace_id=workspace_id, role="member")
    colleague_id = await seed_member(db, workspace_id=workspace_id, role="member")
    owner = _caller(owner_id, workspace_header=workspace_id, request_ref="req-7")

    # A model-supplied project_id is not an input: the item lands in the connection's Workspace.
    recorded = await _mcp(db, owner, "memory_remember", text="I prefer short answers.", project_id=other_id)
    assert (recorded["state"], recorded["author_class"], recorded["memory_state"]) == (
        "recorded",
        "human_stated",
        "observed",
    )
    row = await db.get(KnowledgeMemoryItem, recorded["memory_id"])
    assert (row.project_id, row.owner_user_id, row.turn_ref) == (workspace_id, owner_id, "req-7")
    # Provenance is the grant's MCP auto session.
    session = await db.get(Session, row.session_id)
    assert (session.agent_type, session.user_id) == ("external_agent", owner_id)

    recalled = await _mcp(db, owner, "memory_recall", query="short answers")
    assert (recalled["state"], recalled["kind"], recalled["not_source_evidence"]) == ("ok", "memory", True)
    colleague = _caller(colleague_id, workspace_header=workspace_id)
    assert (await _mcp(db, colleague, "memory_recall", query="short answers"))["state"] == "no_match"

    # The Workspace must come from the connection; outside the grant or membership it is unknown.
    assert (await _mcp(db, _caller(owner_id), "memory_recall"))["state"] == "needs_configuration"
    assert (await _mcp(db, _caller(owner_id, bound_project_ids=(workspace_id,)), "memory_recall"))["state"] == "ok"
    assert (await _mcp(db, _caller(owner_id, workspace_header=other_id), "memory_recall"))["state"] == "not_found"
    bound_elsewhere = _caller(owner_id, bound_project_ids=(other_id,), workspace_header=workspace_id)
    assert (await _mcp(db, bound_elsewhere, "memory_recall"))["state"] == "not_found"
    read_only = _caller(owner_id, workspace_header=workspace_id, scopes=("knowledge:read",))
    assert (await _mcp(db, read_only, "memory_remember", text="Remember this."))["state"] == "denied"
    # The fixed refusals of the chat tool hold over MCP too.
    secret = await _mcp(db, owner, "memory_remember", text="Remember password=Hunter2Hunter2 please.")
    assert (secret["state"], secret["reason"]) == ("denied", "secret_detected")

    # Neither the activity rows nor the audit log keep a copy of the memory text.
    activity = (await db.execute(select(ToolCall.parameters).where(ToolCall.session_id == row.session_id))).scalars()
    audits = (await db.execute(select(AuditLog.details).where(AuditLog.user_id == owner_id))).scalars()
    stored = json.dumps([*activity, *audits])
    assert "short answers" not in stored and "Hunter2" not in stored


async def test_the_mcp_server_offers_the_governed_tools_without_a_workspace_argument():
    from mcp.server.fastmcp import FastMCP

    from app.services.mcp_governed_knowledge_tools import register_governed_knowledge_tools
    from app.services.mcp_knowledge_ledger_tools import register_knowledge_ledger_tools

    server = FastMCP("test")
    register_governed_knowledge_tools(server, lambda ctx: ("u", None, None, ()))
    register_knowledge_ledger_tools(server, lambda ctx: ("u", None, None, ()))
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert set(tools) == {
        "knowledge_search",
        "knowledge_read",
        "knowledge_changes",
        "knowledge_code_impact",
        "memory_recall",
        "memory_remember",
        "episode_summary",
        "jira_release_status",
    }
    for tool in tools.values():
        assert not {"project_id", "workspace_id", "user_id"} & set(tool.inputSchema["properties"])


def test_memory_recall_rides_with_the_governed_knowledge_tools_and_remember_stays_in_the_chat():
    from app.agent.core.context.context_planner import plan_turn_context
    from app.agent.core.context.tool_families import GOVERNED_KNOWLEDGE_TOOLS
    from app.agent.core.context.turn_tool_surface import resolve_turn_tool_surface, resolve_workflow_tool_surface
    from app.services.workflow_contracts.knowledge_request import plan_knowledge_request
    from app.tools.registry import get_all_tools_with_plugins

    knowledge_request = resolve_workflow_tool_surface(
        workflow_id="knowledge_request", workflow_contract=None
    )
    assert "memory_recall" in knowledge_request and "memory_remember" not in knowledge_request
    assert "memory_recall" in GOVERNED_KNOWLEDGE_TOOLS and "memory_remember" not in GOVERNED_KNOWLEDGE_TOOLS
    # The Knowledge request still searches the sources first.
    [first] = plan_knowledge_request(
        {"knowledge_query": "Report Builder"},
        turn_tool_history=[],
        covered_evidence_axes=None,
        allowed_tool_names={"knowledge_search", "memory_recall"},
    )
    assert first["function"]["name"] == "knowledge_search"

    # A plain user-facing chat turn gets the governed default surface, which keeps both memory tools.
    plan = resolve_turn_tool_surface(
        plan_turn_context(project_id="p1", agent_definition=None, session_metadata={}, history_count=0),
        capability_type="diagnosis",
        workflow_id=None,
        workflow_contract=None,
        routing_resolution=None,
        agent_definition=None,
        project_config={},
    )
    assert plan.tool_surface_source == "governed_default" and plan.tool_surface_set == "diagnosis.v10"
    assert {"memory_recall", "memory_remember"} <= set(plan.tool_allowlist)
    catalog = {definition["function"]["name"] for definition in get_all_tools_with_plugins(agent_type="diagnosis")}
    assert {"memory_recall", "memory_remember"} <= catalog
