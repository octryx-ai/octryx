"""A pipeline's green run remembered per folder and tree (``pipeline``): the same commands on the same tree never
run twice."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import os_junk
from .pipeline_commands import REPORTS
from .state import LocalState


def _head(root: Path) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


GREEN_FILE = "pipeline-green.json"


def tree_digest(root: Path) -> str:
    """The git tree of the folder as it is now, uncommitted and untracked files included (``.gitignore`` holds), via a
    throwaway index; ``""`` when git cannot say."""
    import tempfile  # noqa: PLC0415

    index = root / ".git" / "index"
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "index"
        if index.is_file():
            shutil.copy2(index, copy)  # keeps the index mtime: git re-reads entries as old as it (racy git)
        env = {**os.environ, "GIT_INDEX_FILE": str(copy)}
        try:
            subprocess.run(["git", "-C", str(root), *os_junk.add_all(), f":(exclude){REPORTS}"], env=env,
                           capture_output=True, timeout=120, check=True)
            done = subprocess.run(["git", "-C", str(root), "write-tree"], env=env, capture_output=True, text=True,
                                  timeout=60, check=True)
        except (OSError, subprocess.SubprocessError):
            return ""
    return done.stdout.strip()


def _key(root: Path, tree: str, view: dict[str, Any]) -> str:
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415

    what = {"folder": str(root), "tree": tree, "commands": view.get("commands"), "path": view.get("path"),
            "browser": view.get("browser")}
    return hashlib.sha256(json.dumps(what, sort_keys=True, default=str).encode()).hexdigest()


def green_before(state: LocalState, root: Path, tree: str, view: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The results of this pipeline's last green run on exactly this tree, ``None`` when it must run.

    (epic-delivery): no test run the pipeline already ran green on the same code. A high review
    finding the session answers without a change (or a retried pass) would otherwise run the whole suite again, with
    the system tests the slowest part of a story's platform steps."""
    from .state import read_json  # noqa: PLC0415

    if not tree or getattr(state, "root", None) is None:
        return None
    stored = read_json(state.root / GREEN_FILE).get(str(root))
    if not isinstance(stored, dict) or stored.get("key") != _key(root, tree, view):
        return None
    results = stored.get("results")
    return [{**item, "reused_green_run": stored.get("at")} for item in results] if isinstance(results, list) else None


def remember_green(state: LocalState, root: Path, tree: str, view: dict[str, Any],
                   results: list[dict[str, Any]]) -> None:
    """Keep an all-green run's results for its tree (one entry per folder); anything red is forgotten."""
    from .state import read_json, write_private_json  # noqa: PLC0415

    if getattr(state, "root", None) is None:
        return
    green = bool(results) and all(item.get("exit_code") == 0 for item in results)
    stored = read_json(state.root / GREEN_FILE)
    if green and tree:
        stored[str(root)] = {"key": _key(root, tree, view), "at": time.time(), "results": results}
    else:
        stored.pop(str(root), None)
    write_private_json(state.root / GREEN_FILE, stored)
