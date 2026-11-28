"""A failed GitHub/GitLab push says why, not only "git push failed"."""

import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.connectors import github_repository_push as source


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def work(tmp_path: Path, monkeypatch):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    workspace = tmp_path / "workspace"
    clone = workspace / "var" / "repos" / "github" / "acme" / "bench"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    (clone / "app.txt").write_text("v1\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "v1")
    _git(clone, "push", "-q", "origin", "HEAD:main")
    _git(clone, "checkout", "-q", "-b", "feature/x")

    async def allowed(_context, **_kwargs):
        return None

    async def auth(_context):
        return dict(os.environ)

    monkeypatch.setattr(source, "require_github_repository_operation", allowed)
    monkeypatch.setattr(source, "_resolve_github_repo", lambda _context, _params: ("acme", "bench"))
    monkeypatch.setattr(source, "github_clone_url", lambda _context, _owner, _repo: str(origin))
    monkeypatch.setattr(source, "github_git_auth_env_async", auth)
    context = SimpleNamespace(workspace_root=str(workspace), project_config={}, project_ids=["ws"], db=None)
    return origin, clone, context


async def _push(context, clone: Path) -> dict:
    (clone / "change.txt").write_text(f"{len(list(clone.iterdir()))}\n")
    return await source.CommitAndPushGitHubRepositoryBranchTool().execute(
        {"repository": "acme/bench", "local_path": str(clone), "commit_message": "change", "branch_name": "feature/x"},
        context)


@pytest.mark.asyncio
async def test_a_push_onto_a_moved_remote_branch_says_non_fast_forward(tmp_path, work):
    origin, clone, context = work
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    _git(other, "checkout", "-q", "-b", "feature/x")
    (other / "theirs.txt").write_text("theirs\n")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "theirs")
    _git(other, "push", "-q", "origin", "feature/x")
    result = await _push(context, clone)
    assert result["error_code"] == "push_rejected_non_fast_forward", result


@pytest.mark.asyncio
async def test_a_push_a_repository_rule_declines_says_so_and_carries_no_git_output(work):
    origin, clone, context = work
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'GH013: Repository rule violations found for refs/heads/feature/x.' >&2\n"
                    "echo 'https://user:S3cr3t@github.com/acme/bench.git' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    result = await _push(context, clone)
    assert result["error_code"] == "push_declined_by_hook", result
    assert "S3cr3t" not in str(result)
