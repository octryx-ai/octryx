"""Syntax checks, the edit tool's diff and auto-check, and apply_patch execution events."""

from __future__ import annotations

import pytest

from tests.support.new_tools_support import _Ctx

# ── check_file_syntax ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_syntax_valid_python(tmp_path):
    from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

    f = tmp_path / "ok.py"
    f.write_text("x = 1 + 2\nprint(x)\n")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await CheckFileSyntaxTool().execute({"path": str(f)}, ctx)
    assert result["valid"] is True
    assert result["language"] == "python"
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_check_syntax_invalid_python(tmp_path):
    from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

    f = tmp_path / "bad.py"
    f.write_text("def foo(\n    pass\n")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await CheckFileSyntaxTool().execute({"path": str(f)}, ctx)
    assert result["valid"] is False
    assert len(result["errors"]) > 0


@pytest.mark.asyncio
async def test_check_syntax_valid_json(tmp_path):
    from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

    f = tmp_path / "data.json"
    f.write_text('{"key": "value", "num": 42}')
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await CheckFileSyntaxTool().execute({"path": str(f)}, ctx)
    assert result["valid"] is True


@pytest.mark.asyncio
async def test_check_syntax_invalid_json(tmp_path):
    from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

    f = tmp_path / "bad.json"
    f.write_text('{"key": "value",}')  # trailing comma – invalid JSON
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await CheckFileSyntaxTool().execute({"path": str(f)}, ctx)
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_check_syntax_unsupported_extension(tmp_path):
    from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

    f = tmp_path / "readme.md"
    f.write_text("# Hello")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await CheckFileSyntaxTool().execute({"path": str(f)}, ctx)
    assert result["valid"] is None  # no checker


@pytest.mark.asyncio
async def test_check_syntax_missing_file(tmp_path):
    from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await CheckFileSyntaxTool().execute({"path": str(tmp_path / "nope.py")}, ctx)
    assert "error" in result


# ── edit_workspace_file – diff output + auto_check ───────────────────────────


@pytest.mark.asyncio
async def test_edit_returns_diff(tmp_path):
    from app.tools.code_impl._code_edit import EditFileTool

    f = tmp_path / "hello.py"
    f.write_text("x = 1\ny = 2\n")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await EditFileTool().execute(
        {"path": str(f), "old_string": "x = 1", "new_string": "x = 99"},
        ctx,
    )
    assert result["status"] == "edited"
    assert "diff" in result
    assert "-x = 1" in result["diff"]
    assert "+x = 99" in result["diff"]
    assert result["execution_event"]["kind"] == "edit"
    assert result["execution_event"]["status"] == "succeeded"
    assert result["execution_event"]["tool_name"] == "edit_workspace_file"
    assert result["execution_event"]["metadata"]["path"] == str(f)


@pytest.mark.asyncio
async def test_edit_auto_check_valid(tmp_path):
    from app.tools.code_impl._code_edit import EditFileTool

    f = tmp_path / "calc.py"
    f.write_text("a = 1\nb = 2\n")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await EditFileTool().execute(
        {"path": str(f), "old_string": "a = 1", "new_string": "a = 42", "auto_check": True},
        ctx,
    )
    assert result["status"] == "edited"
    assert "syntax_check" in result
    assert result["syntax_check"]["valid"] is True


@pytest.mark.asyncio
async def test_edit_auto_check_invalid(tmp_path):
    from app.tools.code_impl._code_edit import EditFileTool

    f = tmp_path / "broken.py"
    f.write_text("x = 1\n")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await EditFileTool().execute(
        {"path": str(f), "old_string": "x = 1", "new_string": "def foo(\n    pass", "auto_check": True},
        ctx,
    )
    assert result["status"] == "edited"
    assert result["syntax_check"]["valid"] is False


@pytest.mark.asyncio
async def test_edit_failure_returns_execution_event(tmp_path):
    from app.tools.code_impl._code_edit import EditFileTool

    f = tmp_path / "hello.py"
    f.write_text("x = 1\n", encoding="utf-8")
    ctx = _Ctx(workspace_root=str(tmp_path))
    result = await EditFileTool().execute(
        {"path": str(f), "old_string": "missing", "new_string": "x = 99"},
        ctx,
    )

    assert "old_string not found" in result["error"]
    assert result["execution_event"]["kind"] == "edit"
    assert result["execution_event"]["status"] == "failed"
    assert result["execution_event"]["metadata"]["path"] == str(f)


@pytest.mark.asyncio
async def test_apply_patch_returns_begin_and_end_events(tmp_path):
    from app.tools.code_impl._code_patch import ApplyPatchTool

    f = tmp_path / "example.txt"
    f.write_text("old\n", encoding="utf-8")
    ctx = _Ctx(workspace_root=str(tmp_path))
    patch = """--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
"""

    result = await ApplyPatchTool().execute({"patch": patch}, ctx)

    assert result["applied"] == 1
    assert result["errors"] == 0
    assert f.read_text(encoding="utf-8") == "new\n"
    assert [event["status"] for event in result["execution_events"]] == ["started", "succeeded"]
    assert result["execution_event"]["kind"] == "patch"
    assert result["execution_event"]["exit_code"] == 0
    assert result["execution_event"]["metadata"]["files"] == ["example.txt"]


@pytest.mark.asyncio
async def test_apply_patch_failure_returns_end_event(tmp_path):
    from app.tools.code_impl._code_patch import ApplyPatchTool

    (tmp_path / "example.txt").mkdir()
    ctx = _Ctx(workspace_root=str(tmp_path))
    patch = """--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
"""

    result = await ApplyPatchTool().execute({"patch": patch}, ctx)

    assert result["applied"] == 0
    assert result["errors"] == 1
    assert [event["status"] for event in result["execution_events"]] == ["started", "failed"]
    assert result["execution_event"]["kind"] == "patch"
    assert result["execution_event"]["exit_code"] == 1
