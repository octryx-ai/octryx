from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

CREDENTIAL_REMOTE = "https://user:tok@github.com/o/r.git"
STRIPPED_REMOTE = "https://github.com/o/r.git"

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True, text=True)
    return completed.stdout.strip()


def make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "README.md").write_text("# demo\n")
    (repo / "src" / "app.py").write_text("print('hello')\n")
    os.symlink("README.md", repo / "link.md")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "init")
    git(repo, "remote", "add", "origin", CREDENTIAL_REMOTE)
    return repo
