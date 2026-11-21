"""``jira_release_status`` on the Knowledge MCP, next to ``knowledge_search`` (open point K2).

Contract: the MCP tool is the chat's live release status. The Workspace comes only from the
connection (grant binding or ``X-Octryx-Workspace`` header), the scope is ``knowledge:read``,
an explicit Jira deactivation of the Workspace denies it before any Jira call, and the only method
that ever reaches Jira is ``GET``.
"""

from __future__ import annotations

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm.attributes import flag_modified

from app.api.routes.mcp_knowledge import SUPPORTED_KNOWLEDGE_MCP_TOOLS
from app.models import Project
from app.services.knowledge.sources.sync import http as http_module
from app.services.knowledge.sources.sync import jira_release_status as status_module
from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS, READ_SCOPE, McpCaller, run_governed_mcp_tool
from app.services.mcp_knowledge_ledger_tools import register_knowledge_ledger_tools
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import seed_member
from tests.test_knowledge_jira_releases import JIRA, _fake, _setup

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("public_source_dns")


def _caller(user_id: str, **overrides) -> McpCaller:
    values = {"user_id": user_id, "grant_id": "grant-k2", "scopes": (READ_SCOPE,), "client_name": "codex"}
    values.update(overrides)
    return McpCaller(**values)


async def test_jira_release_status_on_mcp_is_live_read_only_and_connection_scoped(db, monkeypatch) -> None:
    authorized, _, _, _ = await _setup(db)
    workspace_id = authorized.project_id
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    jira = _fake()
    fake_transport = httpx.MockTransport(jira.handler)

    def reader(connection, transport=None):
        # The MCP path passes no transport; the real reader runs against the fake Jira.
        return http_module.SourceReader(connection, transport=fake_transport)

    monkeypatch.setattr(status_module, "SourceReader", reader)

    async def status(caller: McpCaller, **arguments):
        payload = {"product": "acme-orders", "version": "v2.4.20", **arguments}
        return await run_governed_mcp_tool(db, caller=caller, tool_name="jira_release_status", arguments=payload)

    answer = await status(_caller(member_id, workspace_header=workspace_id))
    assert (answer["state"], answer["source"], answer["jira_version"]) == ("ok", "live Jira query", "Release 2.4.20")
    assert answer["status_counts"] == {"to_do": 1, "in_progress": 1, "done": 1, "unknown": 0}
    assert [blocker["url"] for blocker in answer["open_blockers"]] == [f"{JIRA}/browse/OPS-2"]
    assert answer["version_url"] == f"{JIRA}/projects/OPS/versions/102"
    # A grant bound to the Workspace needs no header; the answer is the same live query.
    assert (await status(_caller(member_id, bound_project_ids=(workspace_id,))))["state"] == "ok"

    # Authorization is the connection's, exactly as for knowledge_search; no argument can widen it.
    assert (await status(_caller(member_id)))["state"] == "needs_configuration"
    assert (await status(_caller(member_id, workspace_header="foreign-workspace")))["state"] == "not_found"
    elsewhere = _caller(member_id, bound_project_ids=("other",), workspace_header=workspace_id)
    assert (await status(elsewhere))["state"] == "not_found"
    no_scope = _caller(member_id, workspace_header=workspace_id, scopes=("knowledge:write",))
    assert (await status(no_scope))["state"] == "denied"
    ignored = await status(_caller(member_id, workspace_header=workspace_id), project_id="other")
    assert ignored["state"] == "ok"
    unmapped = await status(_caller(member_id, workspace_header=workspace_id), product="billing")
    assert (unmapped["state"], unmapped["reason"]) == ("needs_configuration", "release_product_not_configured")
    assert set(jira.methods) == {"GET"}

    # An explicit Jira deactivation of the Workspace denies the call before anything reaches Jira.
    calls_before = len(jira.methods)
    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "disabled_connectors": ["jira"]}
    flag_modified(project, "config")
    await db.flush()
    refused = await status(_caller(member_id, workspace_header=workspace_id))
    assert (refused["state"], refused["reason"]) == ("denied", "connector_not_active")
    assert len(jira.methods) == calls_before


async def test_jira_release_status_is_registered_next_to_knowledge_search_on_both_transports() -> None:
    server = FastMCP("test")
    register_knowledge_ledger_tools(server, lambda ctx: ("u", None, None, ()))
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert {"knowledge_search", "jira_release_status"} <= set(tools)
    schema = tools["jira_release_status"].inputSchema
    assert set(schema["properties"]) == {"product", "version"} and set(schema["required"]) == {"product", "version"}
    assert GOVERNED_MCP_TOOLS["jira_release_status"][1] == READ_SCOPE
    assert SUPPORTED_KNOWLEDGE_MCP_TOOLS["jira_release_status"]["required_scopes"] == ["knowledge:read"]
