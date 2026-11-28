"""Review & PR: the checkout reviews the existing branch as it is on the remote, never a copy reset to the base."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.platform.dispatch import FAILED, SUCCEEDED, read_outcome


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@e.st", "-c", "user.name=t", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def _remote_with_branch(tmp_path: Path) -> tuple[Path, str, str]:
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "a.py").write_text("x = 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    main = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-qb", "feature/BRD-12")
    (work / "a.py").write_text("x = 2\n")
    _git(work, "commit", "-qam", "change")
    branch = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "main")
    remote = tmp_path / "remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(remote))
    return remote, main, branch


def _prepare_like_the_tool(monkeypatch, tmp_path: Path, remote: Path) -> Path:
    copy = tmp_path / "copy"

    async def dispatch(db, run, tool, arguments, *, capability_class, workspace_root=None):
        _git(tmp_path, "clone", "-q", str(remote), str(copy))
        _git(copy, "checkout", "-q", "-B", arguments["branch_name"])
        return read_outcome({"local_path": str(copy)})

    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    return copy


@pytest.mark.asyncio
async def test_the_review_checkout_takes_the_remote_branch_and_its_merge_base(monkeypatch, tmp_path):
    remote, main, branch = _remote_with_branch(tmp_path)
    copy = _prepare_like_the_tool(monkeypatch, tmp_path, remote)
    run = SimpleNamespace(repository="bitbucket:demo-team/test", branch="feature/BRD-12", context={})

    outcome = await scm.checkout(None, run, {})

    assert outcome.state == SUCCEEDED
    assert _git(copy, "rev-parse", "HEAD") == branch
    assert run.context["base_sha"] == main
    assert _git(copy, "diff", "--stat", main, "HEAD")


@pytest.mark.asyncio
async def test_a_branch_missing_on_the_remote_is_refused_instead_of_reviewing_the_base(monkeypatch, tmp_path):
    remote, _main, _branch = _remote_with_branch(tmp_path)
    _prepare_like_the_tool(monkeypatch, tmp_path, remote)
    run = SimpleNamespace(repository="bitbucket:demo-team/test", branch="feature/BRD-99", context={})

    outcome = await scm.checkout(None, run, {})

    assert outcome.state == FAILED and "not on the remote" in outcome.reason
