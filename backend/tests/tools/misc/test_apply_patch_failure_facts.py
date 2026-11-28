"""apply_patch_workspace reports failures as closed codes and platform-written facts."""

from __future__ import annotations

import pytest

from app.tools.code_impl._code_patch import ApplyPatchTool
from app.tools.context import ToolContext

LEAKY = "boom ghp_X7" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123 at /srv/internal/x7-secret-path"
SOURCE = "one\ntwo\nthree\nfour\nfive\nsix\nseven\n"


def _context(workspace) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={},
        workspace_root=str(workspace),
    )


async def _apply(workspace, patch: str) -> dict:
    return await ApplyPatchTool().execute({"patch": patch}, _context(workspace))


@pytest.mark.asyncio
async def test_hunks_with_context_lines_replace_the_right_lines(tmp_path):
    target = tmp_path / "numbers.txt"
    target.write_text(SOURCE, encoding="utf-8")
    patch = """--- a/numbers.txt
+++ b/numbers.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
@@ -5,3 +5,4 @@
 five
+five-and-a-half
 six
 seven
"""

    result = await _apply(tmp_path, patch)

    assert result["applied"] == 1 and result["errors"] == 0
    assert target.read_text(encoding="utf-8") == "one\nTWO\nthree\nfour\nfive\nfive-and-a-half\nsix\nseven\n"
    assert result["files"][0]["hunks"] == [
        {"hunk_index": 1, "applied_at_line": 1, "offset_lines": 0},
        {"hunk_index": 2, "applied_at_line": 5, "offset_lines": 0},
    ]


@pytest.mark.asyncio
async def test_a_hunk_with_a_wrong_line_number_applies_at_its_one_match(tmp_path):
    target = tmp_path / "numbers.txt"
    target.write_text(SOURCE, encoding="utf-8")
    patch = """--- a/numbers.txt
+++ b/numbers.txt
@@ -1,2 +1,2 @@
 five
-six
+SIX
"""

    result = await _apply(tmp_path, patch)

    assert result["errors"] == 0
    assert "SIX" in target.read_text(encoding="utf-8")
    assert result["files"][0]["hunks"] == [{"hunk_index": 1, "applied_at_line": 5, "offset_lines": 4}]


@pytest.mark.asyncio
async def test_a_hunk_that_does_not_apply_is_facts_and_leaves_the_file(tmp_path):
    target = tmp_path / "numbers.txt"
    target.write_text(SOURCE, encoding="utf-8")
    patch = """--- a/numbers.txt
+++ b/numbers.txt
@@ -1,2 +1,2 @@
 one
-two
+TWO
@@ -4,2 +4,2 @@
 four
-not-in-the-file
+changed
"""

    result = await _apply(tmp_path, patch)

    assert result["applied"] == 0 and result["errors"] == 1
    assert result["files"] == [
        {
            "file": "numbers.txt",
            "error": "patch_hunk_did_not_apply",
            "error_code": "patch_hunk_did_not_apply",
            "hunk_index": 2,
            "expected_line": 4,
            "reason": "context_mismatch",
            "match_count": 0,
        }
    ]
    assert target.read_text(encoding="utf-8") == SOURCE
    assert result["execution_event"]["status"] == "failed"


@pytest.mark.asyncio
async def test_an_invalid_hunk_header_is_a_closed_code(tmp_path):
    (tmp_path / "numbers.txt").write_text(SOURCE, encoding="utf-8")
    patch = "--- a/numbers.txt\n+++ b/numbers.txt\n@@ nonsense @@\n-one\n+ONE\n"

    result = await _apply(tmp_path, patch)

    assert result["files"] == [
        {
            "file": "numbers.txt",
            "error": "patch_hunk_header_invalid",
            "error_code": "patch_hunk_header_invalid",
            "hunk_index": 1,
        }
    ]


@pytest.mark.asyncio
async def test_a_file_read_failure_is_a_closed_code_and_the_class(tmp_path):
    (tmp_path / "example.txt").mkdir()
    patch = "--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-old\n+new\n"

    result = await _apply(tmp_path, patch)

    (entry,) = result["files"]
    assert entry == {
        "file": "example.txt",
        "error": "patch_file_read_failed",
        "error_code": "patch_file_read_failed",
        "error_type": "IsADirectoryError",
    }
    assert "Errno" not in str(result) and str(tmp_path) not in entry["error"]


@pytest.mark.asyncio
async def test_an_unexpected_failure_never_returns_the_exception_text(tmp_path, monkeypatch):
    def explode(self, patch_text, workspace):
        raise RuntimeError(LEAKY)

    monkeypatch.setattr(ApplyPatchTool, "_apply", explode)
    patch = "--- a/x.txt\n+++ b/x.txt\n@@ -0,0 +1 @@\n+x\n"

    result = await _apply(tmp_path, patch)

    assert result["error"] == "patch_apply_failed error_type=RuntimeError"
    assert result["error_code"] == "patch_apply_failed"
    assert result["error_type"] == "RuntimeError"
    assert result["execution_event"]["status"] == "failed"
    for marker in ("ghp_X7fake", "/srv/internal", "boom"):
        assert marker not in str(result)


@pytest.mark.asyncio
async def test_a_new_file_patch_creates_the_file(tmp_path):
    patch = "--- /dev/null\n+++ b/new/hello.txt\n@@ -0,0 +1,2 @@\n+hello\n+world\n"

    result = await _apply(tmp_path, patch)

    assert result["errors"] == 0
    assert (tmp_path / "new" / "hello.txt").read_text(encoding="utf-8") == "hello\nworld\n"
