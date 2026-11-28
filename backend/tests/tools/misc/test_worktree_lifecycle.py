from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.worktree import service as worktree_service_module
from app.services.worktree import worktree_service
from app.tools.context import ToolContext
from app.tools.worktree import WorktreeCleanupTool, WorktreeCommitTool, WorktreeCreateTool, WorktreeMergeTool


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "dev@example.com", cwd=repo)
    _git("config", "user.name", "Dev User", cwd=repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "initial commit", cwd=repo)
    return repo


@pytest.fixture
def isolated_worktree_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(worktree_service_module, "_DATA_DIR", tmp_path / "data")
    worktree_service._worktrees.clear()
    try:
        yield
    finally:
        worktree_service._worktrees.clear()


@pytest.mark.asyncio
async def test_worktree_service_covers_full_lifecycle(tmp_path: Path, isolated_worktree_state) -> None:
    repo = _init_repo(tmp_path)

    session_id = "session-12345678"
    worktree = await worktree_service.create(session_id=session_id, workspace_root=str(repo))

    assert worktree.session_id == session_id
    assert worktree.path.exists()
    assert await worktree_service.get(session_id) == worktree
    assert [item.session_id for item in await worktree_service.list()] == [session_id]

    tracked_file = worktree.path / "README.md"
    tracked_file.write_text("hello from worktree\n", encoding="utf-8")

    diff = await worktree_service.diff(session_id)
    assert "hello from worktree" in diff
    assert "-hello" in diff or "-hello\n" in diff

    commit_sha = await worktree_service.commit(session_id, "worktree change")
    assert len(commit_sha) == 40
    assert _git("rev-parse", "HEAD", cwd=worktree.path) == commit_sha

    merge_sha = await worktree_service.merge_into_main(session_id, target_branch="main")
    assert len(merge_sha) == 40
    assert _git("rev-parse", "HEAD", cwd=repo) == merge_sha
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello from worktree\n"

    removed = await worktree_service.cleanup(session_id)
    assert removed is True
    assert await worktree_service.get(session_id) is None
    assert not worktree.path.exists()
    assert _git("branch", "--list", worktree.branch, cwd=repo) == ""


@pytest.mark.asyncio
async def test_worktree_service_rejects_non_git_root(tmp_path: Path, isolated_worktree_state) -> None:
    with pytest.raises(RuntimeError, match="No git repository found"):
        await worktree_service.create(session_id="session-1", workspace_root=str(tmp_path))


@pytest.mark.asyncio
async def test_worktree_service_cleanup_missing_session_returns_false(isolated_worktree_state) -> None:
    removed = await worktree_service.cleanup("missing-session")
    assert removed is False


@pytest.mark.asyncio
async def test_worktree_create_tool_reports_non_git_root_error(tmp_path: Path, isolated_worktree_state) -> None:
    context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
    )

    result = await WorktreeCreateTool().execute({}, context)

    assert result["error"].startswith("No git repository found")


@pytest.mark.asyncio
async def test_worktree_cleanup_tool_reports_missing_session_as_not_removed(isolated_worktree_state) -> None:
    context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id="missing-session",
        project_config={},
    )

    result = await WorktreeCleanupTool().execute({}, context)

    assert result == {"session_id": "missing-session", "removed": False}


@pytest.mark.asyncio
async def test_agent_commits_and_merges_carry_the_ai_trailers(tmp_path: Path, isolated_worktree_state) -> None:
    repo = _init_repo(tmp_path)
    session_id = "session-ai-marked"
    worktree = await worktree_service.create(session_id=session_id, workspace_root=str(repo))
    context = ToolContext(user_id="user-1", project_ids=[], roles=["admin"], session_id=session_id,
                          project_config={}, turn_model="claude-haiku-5-5")

    (worktree.path / "README.md").write_text("by the agent\n", encoding="utf-8")
    committed = await WorktreeCommitTool().execute({"message": "Fix the totals"}, context)
    assert committed["message"] == "Fix the totals\n\nAI-Generated-By-octryx: claude-haiku-5-5"
    assert _git("log", "-1", "--format=%(trailers:key=AI-Generated-By-octryx,valueonly)", cwd=worktree.path) == (
        "claude-haiku-5-5")

    (worktree.path / "NOTES.md").write_text("pending\n", encoding="utf-8")
    merged = await WorktreeMergeTool().execute({"target_branch": "main"}, context)
    assert "error" not in merged, merged
    for ref in ("HEAD", "HEAD^2"):
        assert "AI-Generated-By-octryx: claude-haiku-5-5" in _git("log", "-1", "--format=%B", ref, cwd=repo)
