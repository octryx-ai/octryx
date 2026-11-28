"""Code intelligence tools for symbol definitions, file outlines, graph summaries, nodes and neighbours."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.support.new_tools_support import _Ctx


@pytest.mark.asyncio
async def test_code_symbol_definition_tool_passes_shared_scope(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code import CodeSymbolDefinitionTool

    captured: dict[str, Any] = {}

    async def fake_find_symbol_definition(**kwargs):
        captured.update(kwargs)
        return {"definitions": [{"path": "src/app.py", "backend": "lsp"}]}

    monkeypatch.setattr("app.services.code_intelligence.queries.find_symbol_definition", fake_find_symbol_definition)
    tool = CodeSymbolDefinitionTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-1"])

    result = await tool.execute({"symbol": "helper", "repository_id": "repo-1"}, context)

    assert result["provenance"]["definition_backends"] == ["lsp"]
    assert captured["repository_id"] == "repo-1"
    assert captured["project_id"] == "project-1"
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["symbol"] == "helper"


@pytest.mark.asyncio
async def test_code_file_outline_tool_returns_http_error_detail(monkeypatch, tmp_path: Path):
    from fastapi import HTTPException

    from app.tools.runtime_impl._runtime_code import CodeFileOutlineTool

    async def fake_get_file_outline(**kwargs):
        raise HTTPException(status_code=404, detail="outline unavailable")

    monkeypatch.setattr("app.services.code_intelligence.outline_queries.get_file_outline", fake_get_file_outline)
    tool = CodeFileOutlineTool()
    context = _Ctx(workspace_root=str(tmp_path))

    result = await tool.execute({"file_path": "src/app.py"}, context)

    assert result == {"error": "outline unavailable"}


@pytest.mark.asyncio
async def test_code_graph_summary_tool_adds_graph_provenance(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeGraphSummaryTool

    captured: dict[str, Any] = {}

    async def fake_get_graph_summary(**kwargs):
        captured.update(kwargs)
        return {
            "graph_backend": "networkx",
            "repository": {"effective_backends": {"graph": "networkx"}},
            "nodes": [],
        }

    monkeypatch.setattr("app.services.code_intelligence.queries.get_graph_summary", fake_get_graph_summary)
    tool = CodeGraphSummaryTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-2"])

    result = await tool.execute({"repository_id": "repo-2"}, context)

    assert result["provenance"]["graph_backend"] == "networkx"
    assert result["provenance"]["repository_effective_backends"]["graph"] == "networkx"
    assert captured["repository_id"] == "repo-2"
    assert captured["project_id"] == "project-2"
    assert captured["cwd"] == tmp_path.resolve()


@pytest.mark.asyncio
async def test_code_node_tool_passes_native_graph_scope(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeNodeTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_node(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {
                "backend": "native",
                "status": "completed",
                "staleness_warnings": [{"path": "src/app.py", "reason": "modified_since_index"}],
            },
            "node": {"name": "handler"},
            "detail": {
                "source_chunk": {
                    "path": "src/app.py",
                    "line_start": 10,
                    "line_end": 14,
                    "content": "10: def handler():\n11:     return service()",
                }
            },
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_queries.get_code_graph_node", fake_get_code_graph_node)
    tool = CodeNodeTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-3"])

    result = await tool.execute(
        {"repository_id": "repo-3", "id": "node-1", "limit": 2, "include_source": True},
        context,
    )

    assert result["provenance"]["graph_backend"] == "native"
    assert any("do not re-read" in item for item in result["agent_guidance"])
    assert any("src/app.py" in item and "read them directly" in item for item in result["agent_guidance"])
    assert captured["repository_id"] == "repo-3"
    assert captured["project_id"] == "project-3"
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["node_id"] == "node-1"
    assert captured["limit"] == 2
    assert captured["include_source"] is True


@pytest.mark.asyncio
async def test_code_neighbors_tool_passes_traversal_bounds(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeNeighborsTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_neighbors(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "nodes": [],
            "edges": [],
        }

    monkeypatch.setattr(
        "app.services.code_intelligence.graph_queries.get_code_graph_neighbors",
        fake_get_code_graph_neighbors,
    )
    tool = CodeNeighborsTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-4"])

    result = await tool.execute(
        {
            "repository_id": "repo-4",
            "query": "handler",
            "relation": "calls",
            "direction": "outgoing",
            "depth": 2,
            "max_nodes": 12,
        },
        context,
    )

    assert result["provenance"]["graph_backend"] == "native"
    assert captured["repository_id"] == "repo-4"
    assert captured["project_id"] == "project-4"
    assert captured["query"] == "handler"
    assert captured["relation"] == "calls"
    assert captured["direction"] == "outgoing"
    assert captured["depth"] == 2
    assert captured["max_nodes"] == 12
