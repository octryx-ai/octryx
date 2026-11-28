"""The platform heals its own cache clone of a repository (``var/repos/...``, scm_cache_clone)."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.connectors import github_repository_prepare as source
from app.tools.connectors.scm_cache_clone import cache_clone_lock


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def remote(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    (seed / "app.txt").write_text("v1\n")
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "v1")
    _git(seed, "push", "-q", "origin", "HEAD:main")

    async def allowed(_context, **_kwargs):
        return None

    async def auth(_context):
        return dict(os.environ)

    monkeypatch.setattr(source, "require_github_repository_operation", allowed)
    monkeypatch.setattr(source, "_resolve_github_repo", lambda _context, _params: ("acme", "bench"))
    monkeypatch.setattr(source, "github_clone_url", lambda _context, _owner, _repo: str(origin))
    monkeypatch.setattr(source, "github_git_auth_env_async", auth)
    return origin, seed


def _context(tmp_path: Path) -> SimpleNamespace:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return SimpleNamespace(workspace_root=str(workspace), project_config={}, project_ids=["ws"], db=None)


async def _prepare(context, branch: str) -> dict:
    return await source.PrepareGitHubRepositoryTool().execute(
        {"repository": "acme/bench", "base_branch": "main", "branch_name": branch}, context)


@pytest.mark.asyncio
async def test_a_diverged_cache_clone_is_healed_onto_the_remote_base(tmp_path, remote):
    origin, seed = remote
    context = _context(tmp_path)
    first = await _prepare(context, "feature/one")
    assert "error" not in first, first
    clone = Path(first["local_path"])
    _git(clone, "checkout", "-q", "main")
    (clone / "local.txt").write_text("left over\n")
    _git(clone, "add", "local.txt")
    _git(clone, "commit", "-q", "-m", "local only")
    (clone / "untracked.txt").write_text("x\n")
    (seed / "app.txt").write_text("v1-rewritten\n")
    _git(seed, "commit", "-q", "-a", "--amend", "-m", "v1 rewritten")
    _git(seed, "push", "-q", "-f", "origin", "HEAD:main")

    second = await _prepare(context, "feature/two")
    assert "error" not in second, second
    assert second["head_commit"] == _git(origin, "rev-parse", "main")
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "feature/two"
    assert not (clone / "local.txt").exists() and not (clone / "untracked.txt").exists()


@pytest.mark.asyncio
async def test_two_parallel_preparations_of_one_repository_both_succeed(tmp_path, remote):
    origin, _seed = remote
    context = _context(tmp_path)
    results = await asyncio.gather(_prepare(context, "feature/a"), _prepare(context, "feature/b"))
    assert all("error" not in result for result in results), results
    assert {result["head_commit"] for result in results} == {_git(origin, "rev-parse", "main")}


@pytest.mark.asyncio
async def test_the_lock_excludes_another_holder_in_this_and_in_another_process(tmp_path):
    clone = tmp_path / "repos" / "bench"
    order: list[str] = []

    async def hold(name: str, seconds: float) -> None:
        async with cache_clone_lock(clone):
            order.append(f"{name}+")
            await asyncio.sleep(seconds)
            order.append(f"{name}-")

    await asyncio.gather(hold("a", 0.3), hold("b", 0.0))
    assert order in (["a+", "a-", "b+", "b-"], ["b+", "b-", "a+", "a-"])

    holder = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR); "
        "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(1.0)"),
        str(clone.parent / ".bench.lock")], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    started = time.monotonic()
    async with cache_clone_lock(clone):
        waited = time.monotonic() - started
    holder.wait(timeout=10)
    assert waited > 0.5  # the other process held it for about 1 s
