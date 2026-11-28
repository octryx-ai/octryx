"""Claude Code parity over MCP for the extra tools: no mode or scope arguments, the connection's Workspace,
the chat's gates, connector reads identical to the chat's, trusted sources, and feedback kept out of the audit."""

from __future__ import annotations

import json
import uuid

import pytest
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.models import AuditLog, Message, Project, Session, ToolCall
from app.models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from app.services.mcp_connector_tools import CONNECTOR_MCP_TOOLS
from app.services.mcp_extra_registration import register_extra_tools
from app.services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS, EXTRA_HANDLER_MCP_TOOLS
from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS, McpCaller, run_governed_mcp_tool
from app.services.mcp_parity_dispatch import PARITY_MCP_TOOLS, run_parity_mcp_tool
from app.services.web_search import health
from app.services.web_search import service as web_search_service
from app.services.web_search.providers import SearchHit
from app.services.web_search.registry import put_source
from app.tools.definitions.surfaces import served_over_mcp
from app.tools.diagram import CreateDiagramTool
from tests.fresh_interpreter_support import run_python_probe
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

SCOPES = ("knowledge:read", "knowledge:write")
GUIDE = "https://docs.example.test/runbook?version=3"
FORBIDDEN_ARGUMENTS = {"mode", "agent_type", "agent_mode", "project_id", "workspace_id", "user_id"}


@pytest.fixture(autouse=True)
def extra_tools(monkeypatch):
    # The parent wires these tables into the runners; the tests do it per test.
    for name, entry in EXTRA_GOVERNED_MCP_TOOLS.items():
        monkeypatch.setitem(GOVERNED_MCP_TOOLS, name, entry)
    for name, entry in EXTRA_HANDLER_MCP_TOOLS.items():
        monkeypatch.setitem(PARITY_MCP_TOOLS, name, entry)


def _caller(user_id: str, workspace_id: str | None, **overrides) -> McpCaller:
    values = {"user_id": user_id, "grant_id": f"grant-{user_id[:8]}", "scopes": SCOPES,
              "workspace_header": workspace_id, "client_name": "claude-code"}
    values.update(overrides)
    return McpCaller(**values)


async def _workspace(db, config: dict) -> str:
    workspace_id = await seed_workspace(db)
    (await db.get(Project, workspace_id)).config = config
    await db.flush()
    return workspace_id




async def test_the_extra_tools_have_no_mode_and_no_identity_arguments():
    server = FastMCP("parity-test")
    register_extra_tools(server, lambda ctx: ("u", None, None, SCOPES))
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == set(CONNECTOR_MCP_TOOLS) | {"web_fetch"}
    # The rest have no gate of their own on MCP: registry tools the session MCP endpoint serves (``surfaces``).
    assert all(served_over_mcp(name) for name in {*EXTRA_GOVERNED_MCP_TOOLS, *EXTRA_HANDLER_MCP_TOOLS} - set(tools))
    assert "office_file_action" not in tools
    for name, tool in tools.items():
        assert not FORBIDDEN_ARGUMENTS & set(tool.inputSchema.get("properties") or {}), name
        assert "X-Octryx-Workspace" in (tool.description or ""), name


def test_the_tool_tables_can_be_merged_by_the_runners_without_an_import_cycle():
    code = (
        "import sys, app.services.mcp_extra_tools; "
        "print(any(m in sys.modules for m in ('app.services.mcp_governed_knowledge', 'app.services.mcp_parity_dispatch')))"
    )
    out = run_python_probe(code)
    assert out.returncode == 0 and out.stdout.strip().splitlines()[-1] == "False"




async def test_a_diagram_is_the_chat_payload(db):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()
    cell = ('<mxCell id="n1" value="EKS" style="rounded=1;" vertex="1" parent="1">'
            '<mxGeometry x="80" y="80" width="160" height="60" as="geometry"/></mxCell>')
    arguments = {"xml": cell, "title": "Topology"}

    result = await run_governed_mcp_tool(
        db, caller=_caller(member_id, workspace_id), tool_name="create_diagram", arguments=dict(arguments)
    )
    chat = await CreateDiagramTool().execute(dict(arguments), None)
    assert set(result) == set(chat)
    assert (result["status"], result["format"], result["diagram_xml"]) == ("created", "drawio", chat["diagram_xml"])


async def test_web_search_and_fetch_hold_the_trusted_source_rule(db, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    health._quarantine.clear()
    workspace_id = await _workspace(
        db, {"data_policy": {"classification": "internal"}, "web_search_policy": {"mode": "trusted_only"}}
    )
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await put_source(db, project_id=workspace_id, pattern="docs.spring.io/spring-boot", state="trusted", user_id=None)
    await db.commit()
    requested: list[list[str]] = []

    async def provider(config, *, query, num_results, include_domains, exclude_domains, code, client_factory):
        requested.append(list(include_domains))
        return [SearchHit("Upgrade", "https://docs.spring.io/spring-boot/upgrading.html", "s"),
                SearchHit("Blog", "https://docs.spring.io/blog/post", "s")]

    monkeypatch.setattr(web_search_service, "search_provider", provider)
    caller = _caller(member_id, workspace_id)
    try:
        found = await run_governed_mcp_tool(db, caller=caller, tool_name="web_search", arguments={"query": "boot 4"})
    finally:
        health._quarantine.clear()
    assert found["state"] == "ok" and found["workspace_search_mode"] == "trusted_only"
    assert [hit["url"] for hit in found["results"]] == ["https://docs.spring.io/spring-boot/upgrading.html"]
    assert found["dropped"]["outside_trusted"] == 1 and requested == [["docs.spring.io"]]

    untrusted = await run_governed_mcp_tool(
        db, caller=caller, tool_name="web_fetch", arguments={"url": "https://example.org/page"}
    )
    assert (untrusted["state"], untrusted["reason"]) == ("denied", "source_not_trusted")
    blocked = await run_governed_mcp_tool(
        db, caller=caller, tool_name="web_fetch", arguments={"url": "https://www.pornhub.com/view"}
    )
    assert (blocked["state"], blocked["reason"]) == ("denied", "source_blocked")


async def test_knowledge_sources_lists_a_seeded_source_with_its_link(db):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    source = KnowledgeEvidenceSource(project_id=workspace_id, source_key="runbook", display_title="Runbook")
    db.add(source)
    await db.flush()
    revision = KnowledgeSourceRevision(
        source_id=source.id, project_id=workspace_id, revision_ordinal=1, content_sha256="0" * 64, byte_size=10,
        media_type="text/markdown", object_bucket="b", object_key="k", parser_name="text", parser_version="1",
        parser_sandbox="none", state=REVISION_STATE_PROJECTED,
    )
    db.add(revision)
    await db.flush()
    db.add(KnowledgeSourceRevisionOrigin(revision_id=revision.id, project_id=workspace_id, source_url=GUIDE))
    await db.commit()

    caller = _caller(member_id, workspace_id)
    listed = await run_parity_mcp_tool(db, caller=caller, tool_name="knowledge_sources", arguments={"limit": 10})
    assert listed["state"] == "ok" and listed["total"] == 1 and listed["next_offset"] is None
    assert listed["sources"] == [{
        "source_id": source.id, "source_key": "runbook", "title": "Runbook", "current_revision": 1,
        "revision_state": REVISION_STATE_PROJECTED, "source_url": GUIDE, "cite_as": f"[Runbook]({GUIDE})",
    }]
    beyond = await run_parity_mcp_tool(db, caller=caller, tool_name="knowledge_sources", arguments={"offset": 1})
    assert beyond["sources"] == []
    bad = await run_parity_mcp_tool(db, caller=caller, tool_name="knowledge_sources", arguments={"limit": 999})
    assert (bad["state"], bad["reason"]) == ("invalid_request", "invalid_page")
    foreign = await run_parity_mcp_tool(
        db, caller=_caller(member_id, await seed_workspace(db)), tool_name="knowledge_sources", arguments={}
    )
    assert foreign["state"] == "not_found"


async def test_feedback_is_recorded_without_its_text_in_audit_or_activity(db):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    session = Session(id=str(uuid.uuid4()), user_id=member_id, project_id=workspace_id, agent_type="chat",
                      metadata_={})
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="An answer.", model="m")
    db.add_all([session, message])
    await db.commit()
    marker = "Clear-steps-" + uuid.uuid4().hex
    arguments = {"session_id": session.id, "message_id": message.id, "rating": "good", "liked": marker,
                 "aspects": {"sources": "liked"}}
    caller = _caller(member_id, workspace_id)

    recorded = await run_parity_mcp_tool(db, caller=caller, tool_name="knowledge_feedback", arguments=arguments)
    await db.commit()
    assert (recorded["state"], recorded["rating"], recorded["aspects"]) == ("recorded", "good", {"sources": "liked"})

    audits = (await db.execute(select(AuditLog))).scalars().all()
    activity = (await db.execute(select(ToolCall).where(ToolCall.tool_name == "knowledge_feedback"))).scalars().all()
    assert audits and activity
    for row in [*audits, *activity]:
        dumped = json.dumps({c.name: getattr(row, c.name) for c in row.__table__.columns}, default=str)
        assert marker not in dumped

    elsewhere = await run_parity_mcp_tool(
        db, caller=_caller(member_id, await seed_workspace(db)), tool_name="knowledge_feedback", arguments=arguments
    )
    assert elsewhere["state"] == "not_found"
    narrow = _caller(member_id, workspace_id, scopes=("knowledge:read",))
    refused = await run_parity_mcp_tool(db, caller=narrow, tool_name="knowledge_feedback", arguments=arguments)
    assert refused["state"] == "denied"
