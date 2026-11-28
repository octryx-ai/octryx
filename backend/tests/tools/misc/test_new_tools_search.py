"""Workspace glob and grep tools: dot resolution, brace patterns, case-insensitive fallback and context lines."""

from __future__ import annotations

import pytest

from tests.support.new_tools_support import _Ctx

# ── grep_workspace – context_lines ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_glob_workspace_files_resolves_dot_against_tool_workspace(tmp_path, monkeypatch):
    from app.tools.code_impl._code_search import GlobFilesTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected = workspace / "src" / "Main.java"
    expected.parent.mkdir()
    expected.write_text("class Main {}\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    unrelated = outside / "Other.java"
    unrelated.write_text("class Other {}\n")
    monkeypatch.chdir(outside)

    ctx = _Ctx(workspace_root=str(workspace))
    result = await GlobFilesTool().execute({"pattern": "**/*.java", "path": "."}, ctx)

    assert result["root"] == str(workspace)
    assert result["files"] == [str(expected)]
    assert str(unrelated) not in result["files"]


@pytest.mark.asyncio
async def test_glob_workspace_files_supports_brace_patterns(tmp_path):
    from app.tools.code_impl._code_search import GlobFilesTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    properties_file = workspace / "src" / "main" / "resources" / "application.properties"
    yml_file = workspace / "src" / "main" / "resources" / "application.yml"
    properties_file.parent.mkdir(parents=True)
    properties_file.write_text("server.port=5000\n")
    yml_file.write_text("server:\n  port: 5000\n")

    ctx = _Ctx(workspace_root=str(workspace))
    result = await GlobFilesTool().execute({"pattern": "**/*.{yml,yaml,properties}", "path": "."}, ctx)

    assert result["root"] == str(workspace)
    assert set(result["files"]) == {str(properties_file), str(yml_file)}


@pytest.mark.asyncio
async def test_glob_workspace_files_falls_back_to_case_insensitive_name_match(tmp_path):
    from app.tools.code_impl._code_search import GlobFilesTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    readme = workspace / "readme.md"
    readme.write_text("# docs\n")

    ctx = _Ctx(workspace_root=str(workspace))
    result = await GlobFilesTool().execute({"pattern": "**/README*", "path": "."}, ctx)

    assert result["root"] == str(workspace)
    assert result["files"] == [str(readme)]


@pytest.mark.asyncio
async def test_grep_workspace_resolves_dot_against_tool_workspace(tmp_path, monkeypatch):
    from app.tools.code_impl._code_search import GrepTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected = workspace / "sample.txt"
    expected.write_text("TARGET\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sample.txt").write_text("TARGET\n")
    monkeypatch.chdir(outside)

    ctx = _Ctx(workspace_root=str(workspace))
    result = await GrepTool().execute({"pattern": "TARGET", "path": "."}, ctx)

    assert result["root"] == str(workspace)
    assert result["count"] == 1
    assert result["matches"][0]["file"] == str(expected)


@pytest.mark.asyncio
async def test_grep_context_lines(tmp_path):
    from app.tools.code_impl._code_search import GrepTool

    f = tmp_path / "sample.txt"
    f.write_text("line1\nline2\nTARGET\nline4\nline5\n")
    ctx = _Ctx(workspace_root=str(tmp_path))

    # Without context_lines: only the matching line
    result_no_ctx = await GrepTool().execute(
        {"pattern": "TARGET", "path": str(tmp_path)},
        ctx,
    )
    assert result_no_ctx["count"] == 1
    assert result_no_ctx["matches"][0]["content"] == "TARGET"

    # With context_lines: either more entries (rg) or embedded context (python fallback)
    result_ctx = await GrepTool().execute(
        {"pattern": "TARGET", "path": str(tmp_path), "context_lines": 1},
        ctx,
    )
    assert result_ctx["count"] >= 1
    combined = " ".join(m["content"] for m in result_ctx["matches"])
    # The combined output must contain the match itself
    assert "TARGET" in combined


@pytest.mark.asyncio
async def test_grep_no_context_lines(tmp_path):
    from app.tools.code_impl._code_search import GrepTool

    f = tmp_path / "data.py"
    f.write_text("before\nfoo = bar\nafter\n")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await GrepTool().execute(
        {"pattern": "foo", "path": str(tmp_path)},
        ctx,
    )
    assert result["count"] == 1
    assert result["matches"][0]["content"] == "foo = bar"
