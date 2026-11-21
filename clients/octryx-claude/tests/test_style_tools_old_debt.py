"""A red formatter or linter that only reports what the files already had before the change is old debt: findings
on lines the change did not add never hold the change red."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from octryx_claude.style_tools import run_tools

pytestmark = pytest.mark.skipif(shutil.which("ruff") is None, reason="needs ruff")
STYLE = {"languages": {"python": {
    "formatter": {"command": "ruff format --check {files}", "enabled": True},
    "linter": {"command": "ruff check --select E501 --line-length 88 {files}", "enabled": True}}}}
OLD = "x = {'a': 1,   'b': 2}\n" + "y = '" + "a" * 90 + "'\n"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "old.py").write_text(OLD)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root, _git(root, "rev-parse", "HEAD")


def _by_kind(results: list[dict]) -> dict:
    return {item["kind"]: item for item in results}


def test_old_problems_of_a_modified_file_are_old_debt_and_new_ones_are_not(tmp_path):
    root, base = _repo(tmp_path)
    (root / "old.py").write_text(OLD + "z = 3\n")  # a clean addition to an unformatted, too-long file
    results = _by_kind(run_tools(root, STYLE, ["old.py"], base=base))
    assert results["formatter"]["state"] == "failed" and results["formatter"]["old_debt"] is True
    assert results["linter"]["state"] == "failed" and results["linter"]["old_debt"] is True
    assert not list(root.glob(".octryx-base-*"))  # the base copy is gone

    (root / "old.py").write_text(OLD + "w = '" + "b" * 95 + "'\n")  # a new long line
    linters = [item for item in run_tools(root, STYLE, ["old.py"], base=base) if item["kind"] == "linter"]
    # (e2e 5c): the change's result names only its own line; the old one comes apart as old debt.
    own, older = linters
    assert own["state"] == "failed" and "old_debt" not in own
    assert "old.py:3:" in own["output"] and "old.py:2:" not in own["output"]
    assert older["old_debt"] is True and "old.py:2:" in older["output"] and "old.py:3:" not in older["output"]


def test_a_new_file_is_never_old_debt(tmp_path):
    root, base = _repo(tmp_path)
    (root / "new.py").write_text(OLD)
    results = _by_kind(run_tools(root, STYLE, ["new.py"], base=base))
    assert "old_debt" not in results["formatter"] and "old_debt" not in results["linter"]


def test_findings_one_per_line_are_split_by_line(tmp_path):
    # ruff concise, flutter analyze and go vet print one finding per line: each line goes to its own side.
    root, base = _repo(tmp_path)
    (root / "old.py").write_text(OLD + "w = '" + "b" * 95 + "'\n")
    concise = {"languages": {"python": {"linter": {
        "command": "ruff check --output-format concise --select E501 --line-length 88 {files}", "enabled": True}}}}
    own, older = run_tools(root, concise, ["old.py"], base=base)
    assert "old.py:3:" in own["output"] and "old.py:2:" not in own["output"] and "old_debt" not in own
    assert older["old_debt"] is True and older["output"].count("old.py:") == 1
