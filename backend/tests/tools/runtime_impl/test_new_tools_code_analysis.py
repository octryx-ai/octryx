"""Code intelligence tools for traces, graph stats and status, god nodes, affected sets and context budgets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.support.new_tools_support import _Ctx


@pytest.mark.asyncio
async def test_code_trace_tool_accepts_source_target_aliases(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeTraceTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_trace(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "path": [{"name": "handler"}, {"name": "service"}],
            "hops": [
                {
                    "index": 0,
                    "source_chunk": {
                        "path": "src/app.py",
                        "line_start": 3,
                        "line_end": 5,
                        "content": "3: def handler():\n4:     return service()",
                    },
                }
            ],
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_path_queries.get_code_graph_trace", fake_get_code_graph_trace)
    tool = CodeTraceTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-5"])

    result = await tool.execute(
        {
            "repository_id": "repo-5",
            "from": "handler",
            "to": "service",
            "direction": "outgoing",
            "max_depth": 3,
            "include_source": True,
        },
        context,
    )

    assert result["provenance"]["graph_backend"] == "native"
    assert any("do not re-read" in item for item in result["agent_guidance"])
    assert captured["repository_id"] == "repo-5"
    assert captured["project_id"] == "project-5"
    assert captured["source"] == "handler"
    assert captured["target"] == "service"
    assert captured["direction"] == "outgoing"
    assert captured["max_depth"] == 3
    assert captured["include_source"] is True


@pytest.mark.asyncio
async def test_code_trace_tool_requires_endpoints(tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeTraceTool

    tool = CodeTraceTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-6"])

    result = await tool.execute({"repository_id": "repo-6", "source": "handler"}, context)

    assert result == {"error": "source and target are required"}


@pytest.mark.asyncio
async def test_code_graph_stats_tool_passes_limit(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeGraphStatsTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_stats(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "stats": {"node_count": 4},
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_analytics.get_code_graph_stats", fake_get_code_graph_stats)
    tool = CodeGraphStatsTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-7"])

    result = await tool.execute({"repository_id": "repo-7", "limit": 4}, context)

    assert result["provenance"]["graph_backend"] == "native"
    assert captured["repository_id"] == "repo-7"
    assert captured["project_id"] == "project-7"
    assert captured["limit"] == 4


@pytest.mark.asyncio
async def test_code_graph_status_tool_passes_repository_scope(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeGraphStatusTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_status(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "latest_run": {"node_count": 4},
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_queries.get_code_graph_status", fake_get_code_graph_status)
    tool = CodeGraphStatusTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-7"])

    result = await tool.execute({"repository_id": "repo-7"}, context)

    assert result["provenance"]["graph_backend"] == "native"
    assert captured["repository_id"] == "repo-7"
    assert captured["project_id"] == "project-7"
    assert captured["cwd"] == tmp_path.resolve()


@pytest.mark.asyncio
async def test_code_god_nodes_tool_passes_filters(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeGodNodesTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_god_nodes(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "nodes": [],
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_analytics.get_code_graph_god_nodes", fake_get_code_graph_god_nodes)
    tool = CodeGodNodesTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-8"])

    result = await tool.execute(
        {"repository_id": "repo-8", "relation": "calls", "node_type": "function", "limit": 3},
        context,
    )

    assert result["provenance"]["graph_backend"] == "native"
    assert captured["repository_id"] == "repo-8"
    assert captured["project_id"] == "project-8"
    assert captured["relation"] == "calls"
    assert captured["node_type"] == "function"
    assert captured["limit"] == 3


@pytest.mark.asyncio
async def test_code_affected_tool_passes_traversal_params(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeAffectedTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_affected(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "affected_nodes": [],
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_analytics.get_code_graph_affected", fake_get_code_graph_affected)
    tool = CodeAffectedTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-9"])

    result = await tool.execute(
        {
            "repository_id": "repo-9",
            "id": "node-9",
            "relation": "calls",
            "direction": "incoming",
            "depth": 3,
            "max_nodes": 20,
        },
        context,
    )

    assert result["provenance"]["graph_backend"] == "native"
    assert captured["repository_id"] == "repo-9"
    assert captured["project_id"] == "project-9"
    assert captured["node_id"] == "node-9"
    assert captured["relation"] == "calls"
    assert captured["direction"] == "incoming"
    assert captured["depth"] == 3
    assert captured["max_nodes"] == 20


@pytest.mark.asyncio
async def test_code_context_tool_passes_budget_params(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeContextTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_context(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "context_nodes": [],
            "budget": {"requested_chars": 1234},
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_context.get_code_graph_context", fake_get_code_graph_context)
    tool = CodeContextTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-10"])

    result = await tool.execute(
        {
            "repository_id": "repo-10",
            "query": "handler",
            "direction": "both",
            "depth": 4,
            "max_nodes": 30,
            "budget_chars": 1234,
        },
        context,
    )

    assert result["provenance"]["graph_backend"] == "native"
    assert captured["repository_id"] == "repo-10"
    assert captured["project_id"] == "project-10"
    assert captured["query"] == "handler"
    assert captured["direction"] == "both"
    assert captured["depth"] == 4
    assert captured["max_nodes"] == 30
    assert captured["budget_chars"] == 1234
