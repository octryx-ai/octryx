"""Shared main folder, op and run branch helpers for the parallel_work git tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitrepo import git

RUN_BRANCH = "feature/CHEF-3-search"


def _main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n  name = t\n  email = t@example.test\n[commit]\n  gpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    main = tmp_path / "kitchen"
    main.mkdir()
    (main / "app.py").write_text("ROUTES = []\n")
    git(main, "init", "-q", "-b", RUN_BRANCH)
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "base")
    return main, git(main, "rev-parse", "HEAD")


def _op(op: str, key: str) -> dict:
    return {"op": op, "key": key, "branch": f"{RUN_BRANCH}--{key}"}
