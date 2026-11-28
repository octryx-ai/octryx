from pathlib import Path

import pytest

from app.tools.context import ToolContext
from app.tools.runtime_impl._runtime_code import CodeSearchRepositoryTool
from app.tools.runtime_impl._runtime_code_git_tools import GitFileIntelligenceTool


@pytest.mark.asyncio
async def test_code_search_tool_uses_runtime_monkeypatch_with_resolver(tmp_path: Path, monkeypatch):
    async def fake_search_repository_code(**kwargs):
        return {
            "repository": {"id": "repo-1", "effective_backends": {"index": "zoekt", "semantic": "regex"}},
            "query": kwargs["query"],
            "search_backend": "zoekt",
            "text_matches": [{"path": "src/app.py", "line": 1, "column": 5, "preview": "def helper():"}],
            "symbol_matches": [],
            "total_text_matches": 1,
            "total_symbol_matches": 0,
            "engines": {"index_backend": "zoekt", "semantic_backend": "regex"},
        }

    monkeypatch.setattr(
        "app.services.code_intelligence.queries.search_repository_code",
        fake_search_repository_code,
        raising=False,
    )
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


@pytest.mark.asyncio
async def test_git_file_intelligence_tool_uses_runtime_monkeypatch_with_resolver(tmp_path: Path, monkeypatch):
    async def fake_git_file_intelligence(**kwargs):
        return {"file": kwargs["file_path"], "summary": "ok"}

    monkeypatch.setattr(
        "app.services.git_intelligence_service.git_file_intelligence",
        fake_git_file_intelligence,
        raising=False,
    )
    tool = GitFileIntelligenceTool()
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await tool.execute({"file": "src/app.py"}, context)

    assert result["file"] == "src/app.py"
    assert result["summary"] == "ok"
