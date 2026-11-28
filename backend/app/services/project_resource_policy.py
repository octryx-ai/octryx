"""Shared policy helpers for project-scoped resources."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CodeRepository, Project

RepositoryOperation = Literal["read", "branch", "write", "pr", "index", "migration"]

REPOSITORY_OPERATION_KEYS: tuple[RepositoryOperation, ...] = (
    "read",
    "branch",
    "write",
    "pr",
    "index",
    "migration",
)

DEFAULT_REPOSITORY_OPERATIONS: dict[RepositoryOperation, bool] = {
    "read": True,
    "branch": False,
    "write": False,
    "pr": False,
    "index": True,
    "migration": False,
}


def normalize_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def normalize_repository_operations(value: Any) -> dict[RepositoryOperation, bool]:
    raw = normalize_mapping(value)
    return {
        key: bool(raw[key]) if key in raw else default
        for key, default in DEFAULT_REPOSITORY_OPERATIONS.items()
    }


def normalize_knowledge_mounts(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    mounts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        source_project_id = str(item.get("source_project_id") or "").strip()
        if not source_project_id or source_project_id in seen:
            continue
        seen.add(source_project_id)
        mounts.append(
            {
                "source_project_id": source_project_id,
                "mount_label": str(item.get("mount_label") or "").strip(),
                "access": "read",
            }
        )
    return mounts


async def resolve_readable_knowledge_project_ids(db: AsyncSession, *, project_id: str | None) -> list[str]:
    base_project_id = str(project_id or "").strip()
    if not base_project_id:
        return []
    project = await db.get(Project, base_project_id)
    if project is None:
        return []
    project_ids = [project.id]
    config = normalize_mapping(project.config)
    mount_ids = [
        mount["source_project_id"]
        for mount in normalize_knowledge_mounts(config.get("knowledge_mounts"))
        if mount["source_project_id"] != project.id
    ]
    if not mount_ids:
        return project_ids
    active_source_ids = {
        row.id
        for row in (
            await db.execute(select(Project).where(Project.id.in_(mount_ids), Project.is_active.is_(True)))
        ).scalars()
    }
    for source_project_id in mount_ids:
        if source_project_id in active_source_ids and source_project_id not in project_ids:
            project_ids.append(source_project_id)
    return project_ids


def repository_operation_policy(repo: CodeRepository) -> dict[RepositoryOperation, bool]:
    config = normalize_mapping(repo.config_json)
    return normalize_repository_operations(config.get("operation_policy"))


def require_repository_operation(repo: CodeRepository, operation: RepositoryOperation) -> None:
    if repository_operation_policy(repo).get(operation, False):
        return
    _deny_repository_operation(operation, "operation is disabled by the configured repository policy")


def _deny_repository_operation(operation: RepositoryOperation, reason: str) -> None:
    raise HTTPException(
        status_code=403,
        detail=f"Repository operation '{operation}' is denied by project repository policy: {reason}",
    )


def _repository_match_terms(repo: CodeRepository) -> set[str]:
    terms: set[str] = set()
    for value in (repo.name, repo.repo_root, repo.remote_url, repo.default_branch):
        text = str(value or "").strip().lower()
        if text:
            terms.add(text)
    # Workspace checkouts slugify the repository name (PROJECT/repo ->
    # project-repo); that directory name must match the configured repository
    # or every workspace-local write is denied as "not configured".
    repo_name = str(repo.name or "").strip().lower()
    if "/" in repo_name:
        terms.add(repo_name.replace("/", "-"))
    repo_root_name = str(repo.repo_root or "").strip().rstrip("/").split("/")[-1].lower()
    if repo_root_name:
        terms.add(repo_root_name.removesuffix(".git"))
    remote_url = str(repo.remote_url or "").strip().lower().removesuffix(".git")
    if remote_url:
        terms.add(remote_url)
        for marker in ("/scm/", "/repos/", "/"):
            if marker in remote_url:
                tail = remote_url.rsplit(marker, 1)[-1].strip("/")
                if tail:
                    terms.add(tail)
    return {term.removesuffix(".git") for term in terms if term}


def _matches_repository_reference(repo: CodeRepository, references: set[str]) -> bool:
    if not references:
        return False
    terms = _repository_match_terms(repo)
    for reference in references:
        normalized_reference = reference.strip().lower().removesuffix(".git").strip("/")
        if not normalized_reference:
            continue
        if normalized_reference in terms:
            return True
        if any(term.endswith(f"/{normalized_reference}") for term in terms):
            return True
    return False


SNAPSHOT_PROVIDER = "knowledge_snapshot"


async def _snapshot_record(db: AsyncSession, project_ids: list[str], provider: str,
                           references: set[str]) -> CodeRepository | None:
    # Its own operation policy decides: the record carries no provider or remote of its own.
    from ..models.project.knowledge_source_sync import KnowledgeSourceConnector
    from .workflow_routing.phased_start_repository import run_reference

    repos = list((await db.execute(select(CodeRepository).where(
        CodeRepository.project_id.in_(project_ids), CodeRepository.provider == SNAPSHOT_PROVIDER,
        CodeRepository.is_active.is_(True)))).scalars())
    for repo in repos:
        source_id = str(dict(normalize_mapping(repo.config_json).get("central_source") or {}).get("connector_id") or "")
        source = await db.get(KnowledgeSourceConnector, source_id) if source_id else None
        if source is None or source.project_id not in project_ids:
            continue
        ref = run_reference(repo, {source.id: source}) or ""
        kind, _, path = ref.partition(":")
        scope = source.scope if isinstance(source.scope, dict) else {}
        remote = urlparse(str(scope.get("remote") or "")).path.strip("/").lower().removesuffix(".git")
        if kind == provider and {path.lower(), remote} & references:
            return repo
    return None


async def require_project_repository_operation(
    db: AsyncSession | None,
    *,
    project_ids: list[str] | None,
    provider: str,
    operation: RepositoryOperation,
    repository_refs: list[str],
) -> None:
    if db is None:
        _deny_repository_operation(operation, "repository policy database session is unavailable")
    normalized_project_ids = [str(item or "").strip() for item in (project_ids or []) if str(item or "").strip()]
    normalized_provider = str(provider or "").strip().lower()
    references = {
        str(item or "").strip().lower().removesuffix(".git").strip("/")
        for item in repository_refs
        if str(item or "").strip()
    }
    if not normalized_project_ids:
        _deny_repository_operation(operation, "project scope is missing")
    if not normalized_provider:
        _deny_repository_operation(operation, "provider is missing")
    if not references:
        _deny_repository_operation(operation, "repository reference is missing")
    rows = (
        await db.execute(
            select(CodeRepository).where(
                CodeRepository.project_id.in_(normalized_project_ids),
                CodeRepository.provider == normalized_provider,
                CodeRepository.is_active.is_(True),
            )
        )
    ).scalars()
    for repo in rows:
        if _matches_repository_reference(repo, references):
            require_repository_operation(repo, operation)
            return
    snapshot = await _snapshot_record(db, normalized_project_ids, normalized_provider, references)
    if snapshot is not None:
        require_repository_operation(snapshot, operation)
        return
    # A repository the Workspace registered through a connection (Knowledge › Add repository) counts too
    # (otherwise scm.create_branch on a registered read_write repository is "not configured"). Its access
    # mode decides: read_only allows reading only, read_write every operation.
    from .knowledge.sources.repository_access import registered_access_mode

    mode = await registered_access_mode(db, normalized_project_ids, references)
    if mode == "read_write" or (mode == "read_only" and operation == "read"):
        return
    if mode == "read_only":
        _deny_repository_operation(operation, "the repository is registered read-only in this Workspace")
    _deny_repository_operation(operation, "repository is not configured for this project/provider")


__all__ = [
    "DEFAULT_REPOSITORY_OPERATIONS",
    "REPOSITORY_OPERATION_KEYS",
    "RepositoryOperation",
    "normalize_mapping",
    "normalize_knowledge_mounts",
    "normalize_repository_operations",
    "repository_operation_policy",
    "require_project_repository_operation",
    "require_repository_operation",
    "resolve_readable_knowledge_project_ids",
]
