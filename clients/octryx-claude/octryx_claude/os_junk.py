"""Operating-system files (``.DS_Store``, ``Thumbs.db``, ...) never enter a tree or patch built from a working copy.

The list is data (``os_junk.json``, shipped in the package and read by the platform's own working-copy tree as
well), turned into git pathspec excludes for every ``git add -A`` that builds the device's state: the change
(``run_contract``), the pipeline's tree (``pipeline.tree_digest``) and the hand-over commit (``work_state``). They hold
whatever the repository's ``.gitignore`` says, and a tracked file keeps its committed version (the index starts
from HEAD).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

DATA = Path(__file__).with_name("os_junk.json")


@cache
def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


@cache
def excludes() -> tuple[str, ...]:
    """Pathspec excludes (``:(exclude,glob)``) for the listed files and folders, at any depth."""
    data = _data()
    files = tuple(f":(exclude,glob)**/{name}" for name in data["files"])
    folders = tuple(f":(exclude,glob)**/{name}/**" for name in data["folders"])
    return files + folders


def add_all() -> tuple[str, ...]:
    """``git add -A`` of the whole working copy without the operating system's files."""
    return ("add", "-A", "--", ".", *excludes())


__all__ = ["DATA", "add_all", "excludes"]
