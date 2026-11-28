"""Code search and impact analysis provenance, summary domain coverage, turn diff tracking and the system prompt."""

from pathlib import Path

import pytest

from app.tools.context import ToolContext
from app.tools.runtime_impl._runtime_code import CodeImpactAnalysisTool, CodeSearchRepositoryTool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_code_search_tool_adds_provenance(monkeypatch, tmp_path: Path):
    async def fake_search_repository_code(**kwargs):
        return {
            "repository": {"id": "repo-1", "effective_backends": {"index": "zoekt", "semantic": "regex"}},
            "query": "helper",
            "search_backend": "zoekt",
            "text_matches": [{"path": "src/app.py", "line": 1, "column": 5, "preview": "def helper():"}],
            "symbol_matches": [],
            "total_text_matches": 1,
            "total_symbol_matches": 0,
            "engines": {"index_backend": "zoekt", "semantic_backend": "regex"},
        }

    monkeypatch.setattr("app.services.code_intelligence.queries.search_repository_code", fake_search_repository_code)
    tool = CodeSearchRepositoryTool()
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await tool.execute({"query": "helper"}, context)

    assert result["provenance"]["search_backend"] == "zoekt"
    assert result["provenance"]["repository_effective_backends"]["index"] == "zoekt"
    assert result["provenance"]["snapshot_engines"]["index_backend"] == "zoekt"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_code_impact_analysis_tool_adds_definition_and_reference_provenance(monkeypatch, tmp_path: Path):
    async def fake_build_impact_analysis(**kwargs):
        return {
            "repository": {"id": "repo-1", "effective_backends": {"index": "ripgrep", "semantic": "scip"}},
            "symbol": "helper",
            "definitions": [{"path": "src/app.py", "line": 1, "backend": "lsp"}],
            "references": [{"path": "src/usage.py", "line": 2, "backend": "lsp"}],
            "callers": [{"path": "src/usage.py", "line": 2, "backend": "manual"}],
            "reference_count": 1,
            "caller_count": 1,
            "impacted_files": [{"path": "src/usage.py", "match_count": 1}],
            "related_symbols": [],
            "risk": "low",
            "suggested_review_files": ["src/usage.py"],
        }

    monkeypatch.setattr("app.services.code_intelligence.queries.build_impact_analysis", fake_build_impact_analysis)
    tool = CodeImpactAnalysisTool()
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await tool.execute({"symbol": "helper"}, context)

    assert result["provenance"]["definition_backends"] == ["lsp"]
    assert result["provenance"]["reference_backends"] == ["lsp"]
    assert result["provenance"]["caller_backends"] == ["manual"]






