"""The git work of a ``parallel_work`` node: one worktree per work item inside the device's main folder.
Every git operation on the main folder runs here as a launcher step, so one job per thread serializes them."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .contract_change import change
from .platform import SessionContext, call_control_plane
from .run_contract import remember
from .state import LocalState
from .work_git_commit import (
    ITEMS_DIR,
    _error,
    _exclude,
    _git,
    _message,
    commit_all,
    commit_main,
    exclude_runtime_files,
)

# The run an item worktree was started for, in the worktree's own git dir (``.git/worktrees/<key>/``).
RUN_MARKER = "octryx-run"
REPORT_TIMEOUT = 120.0
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_BRANCH = re.compile(r"^(?!-)(?!/)(?!.*\.\.)[A-Za-z0-9._/-]{1,250}$")
_EXCLUDE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def pending(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    view = (contract or {}).get("work_git")
    return view if isinstance(view, dict) and isinstance(view.get("ops"), list) and view["ops"] else None


def item_folder(root: Path, key: str) -> Path:
    return Path(root) / ITEMS_DIR / key


def is_item_folder(folder: str | Path) -> bool:
    return Path(os.path.realpath(folder)).parent.name == ITEMS_DIR



def _worktree_branch(path: Path) -> str:
    done = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return done.stdout.strip() if done.returncode == 0 else ""


def _marker(path: Path) -> Path | None:
    done = _git(path, "rev-parse", "--absolute-git-dir")
    return Path(done.stdout.strip()) / RUN_MARKER if done.returncode == 0 and done.stdout.strip() else None


def _worktree_run(path: Path) -> str:
    marker = _marker(path)
    try:
        return marker.read_text().strip() if marker is not None and marker.is_file() else ""
    except OSError:
        return ""


def _mark_run(path: Path, run_id: str) -> None:
    marker = _marker(path)
    if marker is not None and run_id:
        marker.write_text(run_id + "\n")


def _kept(path: Path, name: str, run_id: str) -> bool:
    # A rerun of a story must not inherit an aborted run's worktrees.
    if not path.is_dir() or _worktree_branch(path) != name:
        return False
    owner = _worktree_run(path)
    return not run_id or owner == run_id


def _conflicted_in(folder: Path) -> list[str]:
    done = _git(folder, "diff", "--name-only", "--diff-filter=U")
    return [line for line in done.stdout.splitlines() if line.strip()]


def _sync(root: Path, path: Path, key: str, trailer: str) -> dict[str, Any]:
    if _git(path, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0:
        return {"conflicts": _conflicted_in(path)}
    if problem := commit_all(path, _message(f"Item {key}", trailer)):
        return {"sync_failed": f"committing the item's worktree failed: {problem}"}
    main_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    if _git(path, "merge-base", "--is-ancestor", main_head, "HEAD").returncode == 0:
        return {}
    done = _git(path, "merge", "--no-ff", "--no-edit", "-m",
                _message(f"Merge the story's work into item {key}", trailer), main_head)
    if done.returncode == 0:
        return {}
    files = _conflicted_in(path)
    if not files:
        _git(path, "merge", "--abort")
        return {"sync_failed": _error(done)}
    return {"conflicts": files}


def environment_dirs(contract: dict[str, Any] | None) -> list[str]:
    prep = dict((contract or {}).get("preparation") or {})
    environment = prep.get("environment") if isinstance(prep.get("environment"), dict) else {}
    tops = []
    for item in (environment or {}).get("path") or []:
        parts = Path(str(item)).parts
        if parts and not os.path.isabs(str(item)) and parts[0] not in ("", ".", "..") and _EXCLUDE_NAME.match(parts[0]):
            tops.append(parts[0])
    return list(dict.fromkeys(tops))


def share_environment(root: Path, path: Path, dirs: list[str]) -> list[str]:
    # A venv per item cost seconds per job; /.venv has no trailing slash because git sees the link as a file.
    linked = []
    for name in dirs:
        source, target = root / name, path / name
        if not source.is_dir() or os.path.lexists(target):
            continue
        try:
            target.symlink_to(source, target_is_directory=True)
        except OSError:
            continue
        linked.append(name)
    if linked:
        _exclude(root, [f"/{name}" for name in linked])
    return linked



def _behind(root: Path, path: Path) -> bool:
    main_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    return _git(path, "merge-base", "--is-ancestor", main_head, "HEAD").returncode != 0


def branch(root: Path, key: str, name: str, trailer: str = "", *, run_id: str = "",
           sync: bool = False, base: str = "", environment: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"op": "branch", "key": key, "branch": name}
    if not _KEY.match(key or "") or not _BRANCH.match(name or ""):
        return {**result, "state": "failed", "detail": "invalid item key or branch"}
    exclude_runtime_files(root)
    problem, kept_files = commit_main(root, _message(f"Work plan before item {key}", trailer), base)
    guarded = {"kept_files": kept_files} if kept_files else {}
    if problem:
        return {**result, **guarded, "state": "failed", "detail": f"committing the main folder failed: {problem}"}
    path = item_folder(root, key)
    if _kept(path, name, run_id):
        synced = _sync(root, path, key, trailer) if sync or _behind(root, path) else {}
        shared = share_environment(root, path, list(environment or []))
        return {**result, **guarded, "state": "branched", "folder": str(path), "kept": True, **synced,
                **({"shared_environment": shared} if shared else {}),
                "head": _git(path, "rev-parse", "HEAD").stdout.strip()}
    foreign = path.is_dir() and _worktree_run(path) != run_id
    if path.exists():
        _git(root, "worktree", "remove", "--force", str(path))
    _git(root, "worktree", "prune")
    # A retry after a conflict keeps the item's own commits (its branch), then gets the main folder merged in;
    # anything else (a first start, an earlier run's leftover) starts fresh from HEAD.
    keep_branch = sync and not foreign and _git(
        root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0
    done = _git(root, "worktree", "add", "-q", str(path), name) if keep_branch else _git(
        root, "worktree", "add", "-q", "-B", name, str(path), "HEAD")
    if done.returncode != 0:
        return {**result, **guarded, "state": "failed", "detail": _error(done)}
    _mark_run(path, run_id)
    synced = _sync(root, path, key, trailer) if keep_branch else {}
    shared = share_environment(root, path, list(environment or []))
    return {**result, **guarded, "state": "branched", "folder": str(path), **synced,
            **({"shared_environment": shared} if shared else {}),
            "head": _git(path, "rev-parse", "HEAD").stdout.strip()}


def merge(root: Path, key: str, name: str, trailer: str = "", *, base: str = "", **_: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"op": "merge", "key": key, "branch": name}
    if not _KEY.match(key or "") or not _BRANCH.match(name or ""):
        return {**result, "state": "failed", "detail": "invalid item key or branch"}
    exclude_runtime_files(root)
    path = item_folder(root, key)
    if path.is_dir() and (problem := commit_all(path, _message(f"Item {key}", trailer))):
        return {**result, "state": "failed", "detail": f"committing the item's worktree failed: {problem}"}
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").returncode != 0:
        return {**result, "state": "failed", "detail": f"the item branch {name} does not exist on this device"}
    problem, kept_files = commit_main(root, _message(f"Work plan before merging item {key}", trailer), base)
    if kept_files:
        result["kept_files"] = kept_files
    if problem:
        return {**result, "state": "failed", "detail": f"committing the main folder failed: {problem}"}
    if _git(root, "merge-base", "--is-ancestor", name, "HEAD").returncode != 0:
        done = _git(root, "merge", "--no-ff", "--no-edit", "-m", _message(f"Merge item {key}", trailer), name)
        if done.returncode != 0:
            files = _conflicted_in(root)
            _git(root, "merge", "--abort")
            return {**result, "state": "conflict" if files else "failed", "files": files, "detail": _error(done)}
    if path.exists():
        _git(root, "worktree", "remove", "--force", str(path))
    _git(root, "worktree", "prune")
    return {**result, "state": "merged", "head": _git(root, "rev-parse", "HEAD").stdout.strip()}


_OPS = {"branch": branch, "merge": merge}


def run(view: dict[str, Any], root: Path, *, base: str, trailer: str = "", run_id: str = "",
        environment: list[str] | None = None) -> dict[str, Any]:
    root = Path(os.path.realpath(root))
    results = []
    for op in view.get("ops") or []:
        kind = str(dict(op).get("op") or "") if isinstance(op, dict) else ""
        if kind not in _OPS:
            results.append({"op": kind, "key": str(dict(op or {}).get("key") or ""), "state": "failed",
                            "detail": "unknown operation"})
            continue
        extra = {"environment": environment} if kind == "branch" and environment else {}
        results.append(_OPS[kind](root, str(op.get("key") or ""), str(op.get("branch") or ""), trailer,
                                  run_id=run_id, sync=op.get("sync") is True, base=base, **extra))
    report: dict[str, Any] = {"node_id": view.get("node_id"), "entry": view.get("entry"), "seq": view.get("seq"),
                              "root": str(root), "results": results}
    if any(item["op"] == "merge" and item["state"] == "merged" for item in results) and base:
        report["change"] = change(root, base)
    return report


def run_for_session(state: LocalState, context: SessionContext, contract: dict[str, Any] | None, folder: str, *,
                    http: Any, trailer: str = "") -> dict[str, Any] | None:
    view = pending(contract)
    if view is None:
        return contract
    base = str(dict((contract or {}).get("facts") or {}).get("base_sha") or "")
    run_id = str(dict((contract or {}).get("run") or {}).get("id") or "")
    report = run(view, Path(folder), base=base, trailer=trailer, run_id=run_id,
                 environment=environment_dirs(contract))
    answer = call_control_plane(state, context, "POST", "/sessions/work-git", http=http, timeout=REPORT_TIMEOUT,
                                body=report)
    return (remember(state, context.session_key, answer.body) or contract) if answer.outcome == "ok" else contract


__all__ = [
    "branch",
    "environment_dirs",
    "is_item_folder",
    "item_folder",
    "merge",
    "pending",
    "run",
    "run_for_session",
    "share_environment",
]
