"""The platform's working-copy tree leaves out the operating system's files, from the launcher's own list.

Finder's ``.DS_Store`` would make the device's tree and the platform's differ (``pipeline_not_for_head``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.workflow_runs import safe_git


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.asyncio
async def test_the_staged_tree_leaves_out_os_files(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "none"))
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("x = 1\n")
    _git(repo, "init", "-q", "-b", "main")
    clean = await safe_git.staged_tree(repo)
    for name in (".DS_Store", "src/._app.py", "src/Thumbs.db", ".Spotlight-V100/Store-V2/x"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(b"\x00finder")

    assert clean and await safe_git.staged_tree(repo) == clean


def test_the_list_is_the_launchers():
    assert ":(exclude,glob)**/.DS_Store" in safe_git.os_junk_excludes()
