from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

CONTRACT_SCHEMA_VERSION = "1.0"
CONTRACT_KIND = "workspace_change_safety_contract"
MAX_CHANGED_FILES = 80


def capture_workspace_change_state(workspace_root: str | Path | None) -> dict[str, Any]:
    if not workspace_root:
        return {"available": False, "reason": "workspace_root_unavailable", "dirty_paths": [], "entries": []}
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"available": False, "reason": "workspace_root_missing", "dirty_paths": [], "entries": []}
    git_root = _git_root(root)
    if git_root is None:
        return {"available": False, "reason": "git_repository_unavailable", "dirty_paths": [], "entries": []}
    entries = _git_status_entries(git_root)
    dirty_paths = sorted({str(entry.get("path") or "") for entry in entries if str(entry.get("path") or "")})
    return {
        "available": True,
        "repo_root": str(git_root),
        "dirty": bool(dirty_paths),
        "dirty_count": len(dirty_paths),
        "dirty_paths": dirty_paths[:MAX_CHANGED_FILES],
        "entries": entries[:MAX_CHANGED_FILES],
        "truncated": len(entries) > MAX_CHANGED_FILES,
    }


def relative_workspace_path(workspace_root: str | Path | None, path: str | Path) -> str:
    root = Path(workspace_root or Path.cwd()).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return target.as_posix()


def relative_change_path(state: dict[str, Any], fallback_root: str | Path | None, path: str | Path) -> str:
    root_value = str(state.get("repo_root") or "").strip()
    if root_value:
        root = Path(root_value).expanduser().resolve()
        target = Path(path).expanduser().resolve()
        try:
            return target.relative_to(root).as_posix()
        except ValueError:
            return target.as_posix()
    return relative_workspace_path(fallback_root, path)


def dirty_target_paths(before_state: dict[str, Any], target_paths: list[str]) -> list[str]:
    dirty = {str(path) for path in before_state.get("dirty_paths") or []}
    return sorted({path for path in target_paths if path in dirty})


def workspace_has_dirty_files(state: dict[str, Any]) -> bool:
    return bool(state.get("available") and state.get("dirty_paths"))


def _git_env() -> dict[str, str]:
    # git on an agent's working copy runs nothing it configures.
    import os

    from .execution_runtime.server_env import with_git_hardening

    return with_git_hardening(os.environ)


def is_validation_command(argv: list[str]) -> bool:
    if not argv:
        return False
    command = Path(str(argv[0])).name.lower()
    args = [str(item).lower() for item in argv[1:]]
    if command in {"pytest", "ruff", "mypy", "eslint", "tsc", "vitest", "jest"}:
        return True
    if command in {"python", "python3"}:
        return any(item in {"pytest", "ruff", "mypy"} or item.endswith(".pytest") for item in args)
    if command in {"npm", "pnpm", "yarn"}:
        return any(item in {"test", "lint", "build", "typecheck"} for item in args)
    if command in {"mvn", "gradle", "go"}:
        return any(item in {"test", "verify", "build", "check"} for item in args)
    if command == "terraform":
        return any(item in {"validate", "fmt"} for item in args)
    return False


def build_workspace_change_contract(
    *,
    tool_name: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None = None,
    target_paths: list[str] | None = None,
    blocked_paths: list[str] | None = None,
    override_dirty: bool = False,
    validation_command: str | list[str] | None = None,
    validation_exit_code: int | None = None,
) -> dict[str, Any]:
    before = before_state or {"available": False, "dirty_paths": [], "entries": []}
    after = after_state or {"available": False, "dirty_paths": [], "entries": []}
    targets = sorted({str(path) for path in (target_paths or []) if str(path)})
    before_dirty = {str(path) for path in before.get("dirty_paths") or []}
    after_dirty = {str(path) for path in after.get("dirty_paths") or []}
    changed_files = _changed_file_entries(after)
    risk_markers = _risk_markers(
        before=before,
        after=after,
        targets=targets,
        blocked_paths=blocked_paths or [],
        override_dirty=override_dirty,
    )
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "kind": CONTRACT_KIND,
        "tool_name": tool_name,
        "git_available": bool(before.get("available") or after.get("available")),
        "repo_root": before.get("repo_root") or after.get("repo_root") or "",
        "target_paths": targets,
        "dirty_before_count": len(before_dirty),
        "dirty_after_count": len(after_dirty),
        "preexisting_dirty_paths": sorted(before_dirty)[:MAX_CHANGED_FILES],
        "changed_files": changed_files,
        "new_dirty_paths": sorted(after_dirty - before_dirty)[:MAX_CHANGED_FILES],
        "preserved_dirty_paths": sorted(before_dirty & after_dirty)[:MAX_CHANGED_FILES],
        "risk_markers": risk_markers,
    }
    if blocked_paths:
        contract["blocked_paths"] = sorted(blocked_paths)
    if validation_command is not None:
        command_text = (
            " ".join(str(part) for part in validation_command)
            if isinstance(validation_command, list)
            else str(validation_command)
        )
        contract["validation"] = {
            "command": command_text,
            "exit_code": validation_exit_code,
            "status": "passed" if validation_exit_code == 0 else "failed",
        }
    if not contract["git_available"]:
        contract["state_reason"] = before.get("reason") or after.get("reason") or "git_repository_unavailable"
    return contract


def _git_root(root: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            env=_git_env(),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def _git_status_entries(git_root: Path) -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "status", "--porcelain=v1"],
            env=_git_env(),  # ``git status`` would run a planted fsmonitor
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    entries: list[dict[str, str]] = []
    for raw_line in result.stdout.splitlines():
        if len(raw_line) < 4:
            continue
        status = raw_line[:2]
        path = raw_line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        entries.append({"status": status, "path": path})
    return entries


def _changed_file_entries(state: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"status": str(entry.get("status") or ""), "path": str(entry.get("path") or "")}
        for entry in (state.get("entries") or [])[:MAX_CHANGED_FILES]
        if isinstance(entry, dict) and str(entry.get("path") or "")
    ]


def _risk_markers(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    targets: list[str],
    blocked_paths: list[str],
    override_dirty: bool,
) -> list[str]:
    markers: list[str] = []
    if not (before.get("available") or after.get("available")):
        markers.append("git_state_unavailable")
    if before.get("dirty_paths"):
        markers.append("workspace_dirty_before")
    if blocked_paths:
        markers.append("preexisting_dirty_target_blocked")
    if override_dirty and before.get("dirty_paths"):
        markers.append("dirty_target_override_used")
    before_dirty = {str(path) for path in before.get("dirty_paths") or []}
    unrelated = before_dirty - set(targets)
    if unrelated:
        markers.append("unrelated_dirty_files_present")
    if after.get("truncated"):
        markers.append("changed_file_list_truncated")
    return markers


__all__ = [
    "build_workspace_change_contract",
    "capture_workspace_change_state",
    "dirty_target_paths",
    "is_validation_command",
    "relative_change_path",
    "relative_workspace_path",
    "workspace_has_dirty_files",
]
