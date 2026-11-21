from __future__ import annotations

import subprocess
from pathlib import Path

from app.services.secure_work.coding.workspace_git import _materialize_local_git_workspace


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.test",
            "HOME": str(cwd),
        },
    )


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _git(["init", "-b", "master"], source)
    (source / "base.txt").write_text("base\n")
    _git(["add", "."], source)
    _git(["commit", "-m", "base"], source)
    _git(["checkout", "-b", "feature/existing-work"], source)
    (source / "feature.txt").write_text("prior delivered work\n")
    _git(["add", "."], source)
    _git(["commit", "-m", "prior work"], source)
    _git(["checkout", "master"], source)
    return source


def test_existing_feature_branch_is_resumed_not_recreated(tmp_path):
    source = _source_repo(tmp_path)
    workspace = tmp_path / "ws-existing"
    workspace.mkdir()
    result = _materialize_local_git_workspace(
        source_root=source,
        workspace_root=workspace,
        feature_branch="feature/existing-work",
        base_branch="master",
    )
    assert result["status"] == "prepared"
    # the workspace resumes the branch state from the prior (declined) delivery
    assert (workspace / "feature.txt").exists()


def test_new_feature_branch_starts_from_base(tmp_path):
    source = _source_repo(tmp_path)
    workspace = tmp_path / "ws-new"
    workspace.mkdir()
    result = _materialize_local_git_workspace(
        source_root=source,
        workspace_root=workspace,
        feature_branch="feature/brand-new",
        base_branch="master",
    )
    assert result["status"] == "prepared"
    assert not (workspace / "feature.txt").exists()
    assert (workspace / "base.txt").exists()
