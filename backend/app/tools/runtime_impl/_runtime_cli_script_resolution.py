"""Script candidate resolution helpers for runtime CLI tools."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ._runtime_cli_repo_resolution import allowed_repo_roots as _allowed_repo_roots_impl

_WORKSPACE_IGNORED_PARTS = {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}
_REPO_IGNORED_PARTS = _WORKSPACE_IGNORED_PARTS | {"target"}
_SCRIPT_EXECUTABLES = {"python", "python3", "bash", "sh", "node"}
_SHELL_CONTROL_TOKENS = ["&&", "||", "|", ";", "$(", "`"]


def _find_workspace_file_candidates(workspace_root: Path, filename: str, *, limit: int = 5) -> list[Path]:
    matches: list[Path] = []
    for candidate in workspace_root.rglob(filename):
        if not candidate.is_file():
            continue
        if any(part in _WORKSPACE_IGNORED_PARTS for part in candidate.parts):
            continue
        matches.append(candidate)
        if len(matches) >= limit:
            break
    return matches


def _find_repo_file_candidates(repo_roots: list[Path], filename: str, *, limit: int = 8) -> list[Path]:
    matches: list[Path] = []
    for repo_root in repo_roots:
        for candidate in repo_root.rglob(filename):
            if not candidate.is_file():
                continue
            if any(part in _REPO_IGNORED_PARTS for part in candidate.parts):
                continue
            matches.append(candidate)
            if len(matches) >= limit:
                return matches
    return matches


def _maybe_resolve_script_command(
    command: str,
    *,
    cwd: Path,
    workspace_root: Path,
    context: ToolContext | None = None,
) -> tuple[str, dict[str, Any] | None, Path]:
    if any(token in command for token in _SHELL_CONTROL_TOKENS):
        return command, None, cwd
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return command, None, cwd
    if len(parts) < 2:
        return command, None, cwd

    executable = Path(parts[0]).name.lower()
    if executable not in _SCRIPT_EXECUTABLES:
        return command, None, cwd

    script_token = parts[1].strip()
    if not script_token or script_token.startswith("-"):
        return command, None, cwd
    script_path = Path(script_token)
    if script_path.is_absolute():
        return command, None, cwd
    if script_path.exists() or (cwd / script_path).exists():
        return command, None, cwd

    repo_roots = _allowed_repo_roots_impl(context, workspace_root) if context is not None else []
    matches = _find_repo_file_candidates(repo_roots, script_path.name) if repo_roots else []
    if not matches:
        matches = _find_workspace_file_candidates(workspace_root, script_path.name)
    resolution = {
        "script": script_token,
        "searched_workspace_root": str(workspace_root),
        "candidate_count": len(matches),
        "candidates": [str(match) for match in matches],
    }
    if len(matches) != 1:
        return command, resolution, cwd

    resolved_parts = list(parts)
    resolved_parts[1] = str(matches[0].name)
    resolved_cwd = matches[0].parent
    return (
        shlex.join(resolved_parts),
        resolution | {"resolved_path": str(matches[0]), "resolved_cwd": str(resolved_cwd)},
        resolved_cwd,
    )
