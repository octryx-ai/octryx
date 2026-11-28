"""The hardcoded Context7 path is denied before connecting or calling, never connects without the server, governs each capability individually and fetches without storing."""

from __future__ import annotations

import pytest

from app.services.mcp_capability_catalog import mirror_mcp_server_capabilities
from app.tools.knowledge_impl._knowledge_fetch import FetchAndSaveKnowledgeTool
from tests.services.mcp.knowledge_fetch_mcp_governance_support import (
    CONTEXT7_RESOLVE,
    _context,
    _enable,
    _install,
    _mcp_tool,
    _RecordingMcpManager,
    _session,
    _workspace,
)

CONTEXT7 = "context7"


CONTEXT7_DOCS = "query-docs"


@pytest.mark.asyncio
async def test_context7_path_is_denied_before_connecting_or_calling(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=CONTEXT7,
        tools=[_mcp_tool(CONTEXT7_RESOLVE), _mcp_tool(CONTEXT7_DOCS)],
    )
    # Only the second capability is enabled, so the first call must already deny.
    await _enable(db, project, CONTEXT7, CONTEXT7_DOCS, risk="read")
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[CONTEXT7])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "context7", "query": "react", "topic": "hooks"},
        context,
    )

    assert result["blocked_by"] == "mcp_capability_policy"
    assert result["mcp_capability"] == CONTEXT7_RESOLVE
    assert manager.calls == []
    assert manager.connects == []


@pytest.mark.asyncio
async def test_context7_never_connects_for_a_project_without_the_server(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "context7", "query": "react", "topic": "hooks"},
        context,
    )

    assert result["blocked_by"] == "mcp_access_policy"
    assert manager.connects == []
    assert manager.calls == []


@pytest.mark.asyncio
async def test_context7_second_capability_is_governed_individually(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=CONTEXT7,
        tools=[_mcp_tool(CONTEXT7_RESOLVE), _mcp_tool(CONTEXT7_DOCS)],
    )
    await _enable(db, project, CONTEXT7, CONTEXT7_RESOLVE, risk="read")
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[CONTEXT7])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "context7", "query": "react", "topic": "hooks"},
        context,
    )

    assert result["reason"] == "mcp_capability_disabled"
    assert result["mcp_capability"] == CONTEXT7_DOCS
    assert manager.calls == [(CONTEXT7, CONTEXT7_RESOLVE, {"libraryName": "react", "query": "hooks"})]
    assert manager.connects == [CONTEXT7]


@pytest.mark.asyncio
async def test_context7_governed_path_fetches_without_storing(db, monkeypatch) -> None:
    project = await _workspace(db)
    user, session = await _session(db, project)
    manager = _RecordingMcpManager()
    _install(monkeypatch, manager)
    await mirror_mcp_server_capabilities(
        db,
        workspace_id=project.id,
        server_name=CONTEXT7,
        tools=[_mcp_tool(CONTEXT7_RESOLVE), _mcp_tool(CONTEXT7_DOCS)],
    )
    await _enable(db, project, CONTEXT7, CONTEXT7_RESOLVE, risk="read")
    await _enable(db, project, CONTEXT7, CONTEXT7_DOCS, risk="read")
    context = _context(db=db, user=user, session=session, project=project, enabled_servers=[CONTEXT7])

    result = await FetchAndSaveKnowledgeTool().execute(
        {"source": "context7", "query": "react", "topic": "hooks"},
        context,
    )

    assert result["status"] == "fetched"
    assert manager.calls == [
        (CONTEXT7, CONTEXT7_RESOLVE, {"libraryName": "react", "query": "hooks"}),
        (CONTEXT7, CONTEXT7_DOCS, {"libraryId": "/facebook/react", "query": "hooks"}),
    ]
    assert manager.connects == [CONTEXT7]
    assert result["saved"] is False
