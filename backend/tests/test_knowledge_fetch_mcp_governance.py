"""MCP governance for ``fetch_and_save_knowledge`` remote calls.

``fetch_and_save_knowledge`` reaches MCP servers itself (``source=mcp`` and the
hardcoded Context7 path). Those calls must pass the same authoritative decision
as registry dispatch — server activation, the workspace capability binding, and
the project approval policy — and a denied or approval-pending capability must
not call the server. The tool is fetch-only: it
returns the content with its ``source_uri`` and stores nothing.
"""

from __future__ import annotations

import pytest

from app.services.mcp_capability_catalog import mirror_mcp_server_capabilities
from app.tools.knowledge_impl._knowledge_fetch import FetchAndSaveKnowledgeTool
from tests.knowledge_fetch_mcp_governance_support import (
    SERVER,
    _context,
    _enable,
    _install,
    _mcp_tool,
    _RecordingMcpManager,
    _session,
    _workspace,
)

READ_TOOL = "read_doc"


WRITE_TOOL = "write_doc"


@pytest.mark.asyncio
async def test_inactive_server_blocks_the_generic_mcp_source(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=SERVER,
        tools=[_mcp_tool(READ_TOOL)],
    )
    await _enable(db, project, SERVER, READ_TOOL, risk="read")
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "mcp", "query": f"{SERVER}/{READ_TOOL}"},
        context,
    )

    assert result["blocked_by"] == "mcp_access_policy"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_disabled_capability_blocks_the_generic_mcp_source(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=SERVER,
        tools=[_mcp_tool(READ_TOOL)],
    )
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[SERVER])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "mcp", "query": f"{SERVER}/{READ_TOOL}"},
        context,
    )

    assert result["blocked_by"] == "mcp_capability_policy"
    assert result["reason"] == "mcp_capability_disabled"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_an_unbound_capability_blocks_the_mcp_source(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=SERVER,
        tools=[_mcp_tool(READ_TOOL)],
    )
    await _enable(db, project, SERVER, READ_TOOL, risk="read")
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[SERVER])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "mcp", "query": f"{SERVER}/{WRITE_TOOL}"},
        context,
    )

    assert result["reason"] == "mcp_capability_not_bound"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_write_capability_requires_approval_before_call(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=SERVER,
        tools=[_mcp_tool(WRITE_TOOL)],
    )
    await _enable(db, project, SERVER, WRITE_TOOL, risk="write")
    context = _context(
        db=db,
        user=user,
        session=session,
        project=project,
        enabled_servers=[SERVER],
        approval_policy={"require_for_risks": ["write"]},
    )

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "mcp", "query": f"{SERVER}/{WRITE_TOOL}", "topic": '{"query": "docs"}'},
        context,
    )

    assert result["approval_required"] is True
    assert result["approval_subject"] == f"mcp__{SERVER}__{WRITE_TOOL}"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_exempting_the_fetch_tool_does_not_waive_the_capability_risk_rule(db, monkeypatch) -> None:
    """The dispatched tool and the capability subject are governed independently."""
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=SERVER,
        tools=[_mcp_tool(WRITE_TOOL)],
    )
    await _enable(db, project, SERVER, WRITE_TOOL, risk="write")
    context = _context(
        db=db,
        user=user,
        session=session,
        project=project,
        enabled_servers=[SERVER],
        approval_policy={"require_for_risks": ["write"], "exempt_tools": ["fetch_and_save_knowledge"]},
    )

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "mcp", "query": f"{SERVER}/{WRITE_TOOL}", "topic": '{"query": "docs"}'},
        context,
    )

    assert result["approval_required"] is True
    assert result["approval_subject"] == f"mcp__{SERVER}__{WRITE_TOOL}"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_governed_read_capability_fetches_without_storing(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=SERVER,
        tools=[_mcp_tool(READ_TOOL)],
    )
    await _enable(db, project, SERVER, READ_TOOL, risk="read")
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[SERVER])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "mcp", "query": f"{SERVER}/{READ_TOOL}", "topic": '{"query": "docs"}'},
        context,
    )

    assert result["status"] == "fetched"
    assert result["content"] == "remote documentation body"
    assert manager.calls == [(SERVER, READ_TOOL, {"query": "docs"})]
    assert result["saved"] is False
