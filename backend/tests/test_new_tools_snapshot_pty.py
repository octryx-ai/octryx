"""The snapshot service and tools and the PTY service."""

from __future__ import annotations

import sys

import pytest

from tests.new_tools_support import _Ctx

# ── snapshot service ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_create_and_restore(tmp_path):
    """Create a snapshot, modify a file, then restore and verify the file reverted."""
    pytest.importorskip("subprocess")  # git must be available
    import subprocess

    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git not available")

    from app.services.snapshot import SnapshotService

    # Write initial file
    target = tmp_path / "readme.txt"
    target.write_text("original content\n")

    svc = SnapshotService(session_id="test-snap", worktree=str(tmp_path))
    await svc.init()
    sha = await svc.track(label="initial")
    assert len(sha) == 40  # full SHA

    # Modify the file and add a new file
    target.write_text("modified content\n")
    (tmp_path / "new_file.txt").write_text("should be deleted on restore\n")

    # Restore
    await svc.restore(sha)

    assert target.read_text() == "original content\n"
    assert not (tmp_path / "new_file.txt").exists()


@pytest.mark.asyncio
async def test_snapshot_diff(tmp_path):
    import subprocess

    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git not available")

    from app.services.snapshot import SnapshotService

    f = tmp_path / "code.py"
    f.write_text("x = 1\n")

    svc = SnapshotService(session_id="test-diff", worktree=str(tmp_path))
    await svc.init()
    sha = await svc.track(label="before")

    f.write_text("x = 999\n")

    diff = await svc.diff(sha)
    assert "-x = 1" in diff or "x = 1" in diff
    assert "x = 999" in diff


# ── PTY service ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="PTY not available on Windows")
async def test_pty_create_and_close():
    """Basic smoke test: create a PTY session and close it."""
    from app.services.pty import PTYManager

    mgr = PTYManager()
    session = await mgr.create(command="/bin/echo")
    assert session.status == "running"
    assert session.pid > 0
    assert session.master_fd > 0
    assert session.execution_runtime["runtime_kind"] == "pty"
    mgr.close(session.id)
    assert session.id not in [s["id"] for s in mgr.list()]


@pytest.mark.skipif(sys.platform == "win32", reason="PTY not available on Windows")
def test_pty_list_empty():
    from app.services.pty import PTYManager

    mgr = PTYManager()
    assert mgr.list() == []


@pytest.mark.skipif(sys.platform == "win32", reason="PTY not available on Windows")
def test_pty_write_to_closed_session():
    from app.services.pty import PTYManager

    mgr = PTYManager()
    # Writing to a non-existent session should be a no-op (no exception)
    mgr.write("nonexistent-id", "ls\n")


# ── snapshot tool classes ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_create_tool_no_db(tmp_path):
    """SnapshotCreateTool should work without a DB (metadata skipped gracefully)."""
    import subprocess

    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git not available")

    from app.tools.code_impl._code_snapshot import SnapshotCreateTool

    (tmp_path / "file.txt").write_text("hello\n")
    ctx = _Ctx(workspace_root=str(tmp_path), session_id="test-123", db=None)
    result = await SnapshotCreateTool().execute({"label": "test"}, ctx)
    assert "sha" in result
    assert result["status"] == "created"
    assert len(result["sha"]) == 40


@pytest.mark.asyncio
async def test_snapshot_list_tool_no_db():
    from app.tools.code_impl._code_snapshot import SnapshotListTool

    ctx = _Ctx(db=None, session_id="xyz")
    result = await SnapshotListTool().execute({}, ctx)
    assert result["snapshots"] == []
    assert result["count"] == 0
