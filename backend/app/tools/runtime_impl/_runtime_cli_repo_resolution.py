"""Repository-root resolution helpers for CLI runtime tools."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext


def normalize_allowed_repos(config: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for entry in config.get("bitbucket_allowed_repos") or []:
        if isinstance(entry, str):
            if "/" not in entry:
                continue
            project_key, repo_slug = entry.split("/", 1)
            entries.append(
                {
                    "project_key": project_key.strip(),
                    "repo_slug": repo_slug.strip(),
                    "enabled": True,
                }
            )
            continue
        if isinstance(entry, dict):
            project_key = str(entry.get("project_key") or entry.get("project") or "").strip()
            repo_slug = str(entry.get("repo_slug") or entry.get("slug") or "").strip()
            if project_key and repo_slug:
                entries.append(
                    {
                        "project_key": project_key,
                        "repo_slug": repo_slug,
                        "enabled": bool(entry.get("enabled", True)),
                    }
                )
    return entries


def managed_repo_root_for_context(context: ToolContext, workspace_root: Path) -> Path:
    configured = str((context.project_config or {}).get("managed_repo_root") or "var/repos/bitbucket").strip()
    root = Path(configured).expanduser()
    repo_base_root = (
        Path(str((context.project_config or {}).get("workspace_root") or workspace_root)).expanduser().resolve()
    )
    resolved = root.resolve() if root.is_absolute() else (repo_base_root / root).resolve()
    if repo_base_root not in resolved.parents and resolved != repo_base_root:
        raise ValueError(f"managed repo root must stay inside workspace root: {repo_base_root}")
    return resolved


def allowed_repo_roots(context: ToolContext, workspace_root: Path) -> list[Path]:
    try:
        base_root = managed_repo_root_for_context(context, workspace_root)
    except ValueError:
        return []
    repo_roots: list[Path] = []
    for entry in normalize_allowed_repos(context.project_config or {}):
        if not entry.get("enabled", True):
            continue
        project_key = str(entry.get("project_key") or "").strip()
        repo_slug = str(entry.get("repo_slug") or "").strip()
        if not project_key or not repo_slug:
            continue
        repo_path = (base_root / project_key / repo_slug).resolve()
        if repo_path.exists() and repo_path.is_dir():
            repo_roots.append(repo_path)
    return repo_roots


def repo_marker_matches(repo_root: Path, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if any(char in marker for char in "*?[]"):
            if any(candidate.is_file() for candidate in repo_root.rglob(marker)):
                return True
            continue
        if (repo_root / marker).exists():
            return True
        if any(candidate.is_file() for candidate in repo_root.rglob(marker)):
            return True
    return False


# Build tool executable -> files that mark a repository it can run in.
_EXECUTABLE_REPO_MARKERS: tuple[tuple[frozenset[str], tuple[str, ...]], ...] = (
    (frozenset({"npm", "npx", "pnpm", "yarn"}), ("package.json",)),
    (frozenset({"mvn", "mvnw"}), ("pom.xml",)),
    (frozenset({"gradle", "gradlew"}), ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")),
    (frozenset({"terraform"}), ("main.tf", "*.tf", ".terraform.lock.hcl")),
)


def _command_parts_for_repo_inference(command: str) -> list[str]:
    """Plain single commands only: a shell composition is never moved into a repository."""
    if any(token in command for token in ["&&", "||", "|", ";", "$(", "`"]):
        return []
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return []


def _markers_for_executable(executable: str) -> tuple[str, ...]:
    for executables, markers in _EXECUTABLE_REPO_MARKERS:
        if executable in executables:
            return markers
    return ()


def _single_git_repo_resolution(repo_roots: list[Path], cwd: Path) -> tuple[dict[str, Any] | None, Path]:
    if len(repo_roots) != 1:
        return None, cwd
    repo_root = repo_roots[0]
    return (
        {
            "mode": "single_allowed_repo",
            "resolved_repo_root": str(repo_root),
            "candidate_count": 1,
            "repo_candidates": [str(repo_root)],
        },
        repo_root,
    )


def infer_repo_cwd_for_command(
    command: str,
    *,
    cwd: Path,
    workspace_root: Path,
    context: ToolContext,
) -> tuple[dict[str, Any] | None, Path]:
    if cwd != workspace_root:
        return None, cwd
    parts = _command_parts_for_repo_inference(command)
    if not parts:
        return None, cwd

    repo_roots = allowed_repo_roots(context, workspace_root)
    if not repo_roots:
        return None, cwd

    executable = Path(parts[0]).name.lower()
    if executable == "git":
        return _single_git_repo_resolution(repo_roots, cwd)
    markers = _markers_for_executable(executable)
    if not markers:
        return None, cwd

    matching_roots = [repo_root for repo_root in repo_roots if repo_marker_matches(repo_root, markers)]
    if len(matching_roots) != 1:
        return (
            (
                {
                    "mode": "repo_marker_search",
                    "markers": list(markers),
                    "candidate_count": len(matching_roots),
                    "repo_candidates": [str(path) for path in matching_roots],
                },
                cwd,
            )
            if matching_roots
            else (None, cwd)
        )

    repo_root = matching_roots[0]
    return (
        {
            "mode": "repo_marker_search",
            "markers": list(markers),
            "resolved_repo_root": str(repo_root),
            "candidate_count": 1,
            "repo_candidates": [str(repo_root)],
        },
        repo_root,
    )
