"""Working-directory resolution for runtime tools: workspace boundary, managed-repo aliases and repo fallback."""

from __future__ import annotations

from pathlib import Path

from app.tools.context import ToolContext

from ...services.repository_bootstrap import find_git_root
from ._runtime_cli_repo_resolution import allowed_repo_roots


def _preferred_repo_roots(context: ToolContext, workspace_root: Path) -> list[Path]:
    roots = list(allowed_repo_roots(context, workspace_root))
    configured_workspace_root = str((context.project_config or {}).get("workspace_root") or "").strip()
    if configured_workspace_root:
        git_root = find_git_root(Path(configured_workspace_root).expanduser().resolve())
        if git_root is not None and git_root.exists() and git_root.is_dir():
            roots.insert(0, git_root)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _resolve_repo_fallback_path(
    *,
    requested_cwd: str | None,
    context: ToolContext,
    workspace_root: Path,
    allow_missing: bool,
) -> Path | None:
    repo_roots = _preferred_repo_roots(context, workspace_root)
    if not repo_roots:
        return None

    normalized_requested = str(requested_cwd or "").strip()
    if normalized_requested in {"", "."}:
        return repo_roots[0] if len(repo_roots) == 1 else None

    requested_path = Path(normalized_requested)
    matches: list[Path] = []
    for repo_root in repo_roots:
        candidate = (
            requested_path.resolve()
            if requested_path.is_absolute()
            else (repo_root / requested_path).resolve()
        )
        if repo_root not in candidate.parents and candidate != repo_root:
            continue
        if allow_missing or candidate.exists():
            matches.append(candidate)

    unique_matches: list[Path] = []
    seen: set[Path] = set()
    for match in matches:
        if match in seen:
            continue
        seen.add(match)
        unique_matches.append(match)
    if len(unique_matches) == 1:
        return unique_matches[0]
    return None


def _resolve_workspace_managed_repo_alias(
    *,
    requested_path: Path,
    workspace_root: Path,
    allow_missing: bool,
) -> Path | None:
    """Map stale absolute managed-repo paths back into the active session workspace.

    Agents sometimes see historical absolute paths from another local run, while
    prepared Bitbucket repositories live below the current session workspace at
    ``var/repos/bitbucket/...``. We never allow direct access to the stale path;
    we only translate the managed-repo suffix when that suffix resolves inside
    the active workspace.
    """

    parts = requested_path.parts
    marker = ("var", "repos", "bitbucket")
    for index in range(0, max(len(parts) - len(marker) + 1, 0)):
        if tuple(parts[index : index + len(marker)]) != marker:
            continue
        alias = (workspace_root / Path(*parts[index:])).resolve()
        if workspace_root not in alias.parents and alias != workspace_root:
            continue
        # Return the alias even when the target file does not exist yet. The
        # caller can then report "path does not exist" against the active
        # workspace path instead of failing the sandbox boundary check for a
        # stale host absolute path from another run.
        if allow_missing or alias.exists() or requested_path.is_absolute():
            return alias
    return None


def _resolve_cwd(
    workspace_root: str | None,
    requested_cwd: str | None,
    *,
    context: ToolContext | None = None,
    allow_repo_fallback: bool = False,
    allow_missing: bool = False,
    prefer_workspace_for_missing: bool = False,
) -> Path:
    root = Path(workspace_root or Path.cwd()).resolve()
    if not requested_cwd:
        requested_cwd = "."
    normalized_requested = str(requested_cwd or "").strip() or "."
    candidate = Path(requested_cwd)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    inside_workspace = root in resolved.parents or resolved == root
    if inside_workspace and resolved.exists() and normalized_requested not in {"", "."}:
        return resolved
    if prefer_workspace_for_missing and inside_workspace and allow_missing:
        return resolved
    if not inside_workspace and candidate.is_absolute():
        alias_candidate = _resolve_workspace_managed_repo_alias(
            requested_path=resolved,
            workspace_root=root,
            allow_missing=allow_missing,
        )
        if alias_candidate is not None:
            return alias_candidate
    if allow_repo_fallback and context is not None:
        repo_candidate = _resolve_repo_fallback_path(
            requested_cwd=normalized_requested,
            context=context,
            workspace_root=root,
            allow_missing=allow_missing,
        )
        if repo_candidate is not None:
            return repo_candidate
    if inside_workspace and (allow_missing or resolved.exists()):
        return resolved
    if not inside_workspace:
        raise ValueError(f"cwd must stay inside workspace root: {root}")
    return resolved

