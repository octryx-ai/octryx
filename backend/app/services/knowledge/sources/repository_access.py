"""What agents may do on a repository a Workspace registered through a connection: ``read_only`` or ``read_write``.
Enforced on the server for every write."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from ..ledger.errors import InvalidEvidenceRequestError
from .sync.git_config import ACCESS_MODE, ACCESS_READ_ONLY, ACCESS_READ_WRITE, HOST_BASE, HOST_KIND
from .sync.git_hosts import (
    BITBUCKET_CLOUD,
    HOST_BITBUCKET_DATACENTER,
    datacenter_base,
    parse_datacenter_repository,
    parse_repository_url,
)

REASON_REPOSITORY_READ_ONLY = "repository_read_only"
ACCESS_UNREGISTERED = "unregistered"
CLOUD_BASE = "https://bitbucket.org"
_CLOUD_HOSTS = frozenset({"bitbucket.org", "api.bitbucket.org"})


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    base: str
    path: str


def identity_of(base_url: object, project_key: object, repo_slug: object) -> RepositoryIdentity | None:
    project = project_key.strip() if isinstance(project_key, str) else ""
    slug = repo_slug.strip().lower() if isinstance(repo_slug, str) else ""
    if not project or not slug or "/" in project or "/" in slug:
        return None
    host = (urlsplit(str(base_url or "")).hostname or "").lower()
    if host in _CLOUD_HOSTS:
        return RepositoryIdentity(CLOUD_BASE, f"{project.lower()}/{slug}")
    base = datacenter_base(base_url)
    if base is None:
        return None
    return RepositoryIdentity(base, f"{project if project.startswith('~') else project.upper()}/{slug}")


def identity_of_remote(remote_url: object, base_url: object) -> RepositoryIdentity | None:
    parts = urlsplit(str(remote_url or "").strip())
    host = (parts.hostname or "").lower()
    # A remote may carry a sign-in (``user:secret@host``): the repository is the same, the userinfo is dropped.
    remote = urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, parts.query, parts.fragment))
    if host in _CLOUD_HOSTS:
        try:
            location = parse_repository_url(remote.removesuffix(".git"), known_host_only=True)
        except InvalidEvidenceRequestError:
            return None
        return RepositoryIdentity(CLOUD_BASE, location.path.lower()) if location.host is BITBUCKET_CLOUD else None
    base = datacenter_base(base_url)
    if base is None:
        return None
    try:
        location = parse_datacenter_repository(remote, base)
    except InvalidEvidenceRequestError:
        return None
    return RepositoryIdentity(base, location.path)


def _registered_identity(scope: dict) -> RepositoryIdentity | None:
    remote = scope.get("remote")
    try:
        if scope.get(HOST_KIND) == HOST_BITBUCKET_DATACENTER:
            base = str(scope.get(HOST_BASE) or "")
            return RepositoryIdentity(base, parse_datacenter_repository(remote, base).path)
        location = parse_repository_url(remote, known_host_only=True)
    except InvalidEvidenceRequestError:
        return None
    return RepositoryIdentity(CLOUD_BASE, location.path.lower()) if location.host is BITBUCKET_CLOUD else None


async def repository_access_mode(db: AsyncSession, project_id: str | None, identity: RepositoryIdentity) -> str:
    if not project_id:
        return ACCESS_UNREGISTERED
    rows = (await db.execute(select(KnowledgeSourceConnector.scope).where(
        KnowledgeSourceConnector.project_id == project_id,
        KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
        KnowledgeSourceConnector.connection_id.is_not(None),
    ))).scalars().all()
    modes = {str((scope or {}).get(ACCESS_MODE) or ACCESS_READ_ONLY) for scope in rows
             if _registered_identity(dict(scope or {})) == identity}
    if not modes:
        return ACCESS_UNREGISTERED
    return ACCESS_READ_WRITE if ACCESS_READ_WRITE in modes else ACCESS_READ_ONLY


async def registered_repositories(db: AsyncSession, project_id: str | None) -> list[dict[str, str]]:
    if not project_id:
        return []
    rows = (await db.execute(select(KnowledgeSourceConnector.scope).where(
        KnowledgeSourceConnector.project_id == project_id,
        KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
        KnowledgeSourceConnector.connection_id.is_not(None),
    ))).scalars().all()
    found: dict[str, dict[str, str]] = {}
    for scope in rows:
        identity = _registered_identity(dict(scope or {}))
        if identity is None or "/" not in identity.path:
            continue
        project_key, repo_slug = identity.path.split("/", 1)
        found[identity.path.lower()] = {"project_key": project_key, "repo_slug": repo_slug, "source": "registered"}
    return list(found.values())


async def registered_access_mode(db: AsyncSession, project_ids: list[str], references: set[str]) -> str | None:
    if not project_ids or not references:
        return None
    rows = (await db.execute(select(KnowledgeSourceConnector.scope).where(
        KnowledgeSourceConnector.project_id.in_(project_ids),
        KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
        KnowledgeSourceConnector.connection_id.is_not(None),
    ))).scalars().all()
    wanted = {ref.strip().lower().removesuffix(".git").strip("/") for ref in references if ref}
    modes: set[str] = set()
    for scope in rows:
        identity = _registered_identity(dict(scope or {}))
        if identity is None:
            continue
        path = identity.path.lower()
        if any(ref == path or ref.endswith(f"/{path}") for ref in wanted):
            modes.add(str((scope or {}).get(ACCESS_MODE) or ACCESS_READ_ONLY))
    if not modes:
        return None
    return ACCESS_READ_WRITE if ACCESS_READ_WRITE in modes else ACCESS_READ_ONLY


async def repository_write_refusal(db: AsyncSession | None, project_id: str | None,
                                   identity: RepositoryIdentity | None) -> str | None:
    if db is None or identity is None:
        return None
    mode = await repository_access_mode(db, project_id, identity)
    return REASON_REPOSITORY_READ_ONLY if mode == ACCESS_READ_ONLY else None


__all__ = [
    "ACCESS_UNREGISTERED",
    "CLOUD_BASE",
    "REASON_REPOSITORY_READ_ONLY",
    "RepositoryIdentity",
    "identity_of",
    "identity_of_remote",
    "registered_access_mode",
    "registered_repositories",
    "repository_access_mode",
    "repository_write_refusal",
]
