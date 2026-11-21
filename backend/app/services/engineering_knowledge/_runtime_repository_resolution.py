"""Repository matching and stack detection for Engineering Knowledge runtime."""

from __future__ import annotations

import re
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import CodeRepository, Project
from ..workspace_root_service import resolve_app_workspace_root
from ._runtime_stack_detection import PRUNE_DIRS, detect_repository_stack_and_versions
from ._runtime_types import RepositoryResolution

_REPO_MARKER_FILES = (
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    ".python-version",
    "package.json",
    "go.mod",
)
_PRUNE_DIRS = PRUNE_DIRS
async def resolve_runtime_repository(
    db: AsyncSession,
    *,
    project_id: str | None,
    repository_id: str | None,
    local_search_roots: list[str | Path] | None = None,
) -> RepositoryResolution:
    """The repository from explicit sources only; the prompt never names it.

    In order: the session's bound repository id; else the single active repository registered for
    the Workspace (or globally); else the single repository under the configured local search
    roots. Several candidates are an ``ambiguous`` resolution and none a missing one: the caller
    turns either into a closed clarification blocker, never into a guess.
    """
    if repository_id:
        repo = await db.get(CodeRepository, repository_id)
        if repo is None or repo.is_active is False:
            return RepositoryResolution(None, "repository id did not resolve")
        return build_repository_resolution(repo, "explicit repository id")

    stmt = select(CodeRepository).where(CodeRepository.is_active.is_(True))
    if project_id:
        stmt = stmt.where(or_(CodeRepository.project_id == project_id, CodeRepository.project_id.is_(None)))
    repos = (await db.execute(stmt.order_by(CodeRepository.name.asc()))).scalars().all()
    if len(repos) == 1:
        return build_repository_resolution(repos[0], "only active repository in scope")
    if repos:
        return RepositoryResolution(None, "several repositories in scope", candidates=candidate_payloads(repos))
    local_repos = await discover_local_repositories(
        db,
        project_id=project_id,
        explicit_roots=local_search_roots,
    )
    if len(local_repos) == 1:
        return build_repository_resolution(local_repos[0], "only repository under the configured search roots")
    if local_repos:
        return RepositoryResolution(
            None,
            "several repositories under the configured search roots",
            candidates=candidate_payloads(local_repos),
        )
    return RepositoryResolution(None, "no repository in scope")


async def discover_local_repositories(
    db: AsyncSession,
    *,
    project_id: str | None,
    explicit_roots: list[str | Path] | None = None,
) -> list[CodeRepository]:
    roots = await resolve_local_search_roots(db, project_id=project_id, explicit_roots=explicit_roots)
    repositories: list[CodeRepository] = []
    seen: set[Path] = set()
    for root in roots:
        for candidate in iter_repository_candidates(root):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            repositories.append(build_discovered_repository(resolved))
    return sorted(repositories, key=lambda repo: (repo.name, repo.repo_root))


async def resolve_local_search_roots(
    db: AsyncSession,
    *,
    project_id: str | None,
    explicit_roots: list[str | Path] | None = None,
) -> list[Path]:
    raw_roots: list[Any] = [*(explicit_roots or [])]
    settings_roots = _split_roots(get_settings().engineering_knowledge_repo_search_roots)
    raw_roots.extend(settings_roots)
    if project_id:
        project = await db.get(Project, project_id)
        config = dict(project.config or {}) if project is not None and isinstance(project.config, dict) else {}
        for key in (
            "engineering_knowledge_repo_search_roots",
            "repository_search_roots",
            "local_repo_search_roots",
            "managed_repo_root",
        ):
            raw_roots.extend(_split_roots(config.get(key)))

    workspace_root = resolve_app_workspace_root()
    roots: list[Path] = []
    for raw_root in raw_roots:
        root = _resolve_root(raw_root, workspace_root=workspace_root)
        if root and root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def iter_repository_candidates(root: Path, *, max_depth: int = 3, max_directories: int = 300) -> list[Path]:
    root = root.expanduser().resolve()
    if _is_repository_root(root):
        return [root]
    candidates: list[Path] = []
    queue: deque[tuple[Path, int]] = deque([(root, 0)])
    visited = 0
    while queue and visited < max_directories:
        directory, depth = queue.popleft()
        visited += 1
        if _is_repository_root(directory):
            candidates.append(directory)
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted((child for child in directory.iterdir() if child.is_dir()), key=lambda item: item.name)
        except OSError:
            continue
        for child in children:
            if child.name in _PRUNE_DIRS or child.name.startswith("."):
                continue
            queue.append((child, depth + 1))
    return candidates


def build_discovered_repository(repo_root: Path) -> CodeRepository:
    return CodeRepository(
        id=f"local:{uuid.uuid5(uuid.NAMESPACE_URL, str(repo_root))}",
        name=repo_root.name,
        repo_root=str(repo_root),
        provider="local_discovered",
        config_json={
            "discovered": True,
            "discovery_source": "engineering_knowledge_runtime",
        },
        capabilities_json={},
        latest_index_summary={},
        is_active=True,
    )


def repository_identifiers(repo: CodeRepository) -> list[str]:
    identifiers = [repo.name, Path(str(repo.repo_root or "")).name]
    if repo.remote_url:
        identifiers.append(str(repo.remote_url).rstrip("/").split("/")[-1].removesuffix(".git"))
    for source in (repo.config_json or {}, repo.capabilities_json or {}, repo.latest_index_summary or {}):
        for key in ("slug", "repo_slug", "repository", "repository_name"):
            value = source.get(key) if isinstance(source, dict) else None
            if value:
                identifiers.append(str(value))
    return [item for index, item in enumerate(identifiers) if item and item not in identifiers[:index]]


def build_repository_resolution(repo: CodeRepository, reason: str) -> RepositoryResolution:
    stack_key, source_versions = detect_repository_stack_and_versions(repo)
    return RepositoryResolution(
        repository=repo,
        match_reason=reason,
        detected_stack_key=stack_key,
        detected_source_versions=source_versions,
        candidates=[],
    )


def candidate_payloads(repos: list[CodeRepository]) -> list[dict[str, str]]:
    return [
        {"id": repo.id, "name": repo.name, "repo_root": repo.repo_root}
        for repo in sorted(repos, key=lambda item: item.name)
    ]


def slug(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text


def _is_repository_root(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in _REPO_MARKER_FILES)


def _split_roots(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,:\n]", text) if part.strip()]


def _resolve_root(value: Any, *, workspace_root: Path) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    try:
        return candidate.resolve()
    except OSError:
        return None
