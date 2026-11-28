"""Focused tests for native Code Graph tools used by coding agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


@dataclass
class _Ctx:
    workspace_root: str | None = None
    session_id: str | None = None
    db: Any = None
    project_config: dict = field(default_factory=dict)
    user_id: str | None = None
    project_ids: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    system_context: str | None = None
    parent_session_id: str | None = None
    sub_agent_depth: int = 0
    agent_definition: Any = None


@pytest.mark.asyncio
async def test_code_explore_tool_returns_compact_graph_context(monkeypatch, tmp_path: Path):
    from app.tools.runtime_impl._runtime_code_graph_tools import CodeExploreTool

    captured: dict[str, Any] = {}

    async def fake_get_code_graph_context(**kwargs):
        captured.update(kwargs)
        return {
            "repository": {"effective_backends": {"graph": "native"}},
            "graph": {"backend": "native", "status": "completed"},
            "context_nodes": [{"node": {"name": "handler"}, "context_text": "src/app.py:10"}],
            "context_files": [
                {
                    "path": "src/app.py",
                    "source_chunks": [
                        {
                            "path": "src/app.py",
                            "line_start": 10,
                            "line_end": 12,
                            "content": "10: def handler():\n11:     return service()",
                        }
                    ],
                }
            ],
            "budget": {"requested_chars": kwargs["budget_chars"]},
        }

    monkeypatch.setattr("app.services.code_intelligence.graph_context.get_code_graph_context", fake_get_code_graph_context)
    tool = CodeExploreTool()
    context = _Ctx(workspace_root=str(tmp_path), project_ids=["project-11"])

    result = await tool.execute(
        {
            "repository_id": "repo-11",
            "query": "handler",
            "depth": 99,
            "max_nodes": 99,
            "budget_chars": 50000,
        },
        context,
    )

    assert result["provenance"]["graph_backend"] == "native"
    assert result["explore_mode"] == "compact_graph_context"
    assert result["agent_guidance"][0].startswith("Use this compact graph exploration")
    assert result["source_files"][0]["path"] == "src/app.py"
    assert result["source_files"][0]["source_chunks"][0]["content"].startswith("10: def handler")
    assert captured["repository_id"] == "repo-11"
    assert captured["project_id"] == "project-11"
    assert captured["query"] == "handler"
    assert captured["depth"] == 4
    assert captured["max_nodes"] == 40
    assert captured["budget_chars"] == 12000


@pytest.mark.asyncio
async def test_code_file_outline_rejects_path_traversal(monkeypatch, tmp_path: Path):
    from fastapi import HTTPException

    from app.services.code_intelligence.outline_queries import get_file_outline

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (tmp_path / "secret.py").write_text("hidden = True\n")

    async def fake_get_repository_snapshot(**_kwargs):
        return {
            "repository": {"id": "repo-1"},
            "snapshot": {"repo_root": str(repo_root), "symbols": [], "engines": {}},
        }

    monkeypatch.setattr(
        "app.services.code_intelligence.outline_queries.get_repository_snapshot",
        fake_get_repository_snapshot,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_file_outline(
            db=None,
            repository_id="repo-1",
            cwd=repo_root,
            project_id="project-1",
            file_path="../secret.py",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "file_path must stay inside the repository root"
