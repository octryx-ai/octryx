"""Routing helpers for design delivery source fetching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CodeRepository
from ..error_facts import error_text
from .bitbucket_fetch import fetch_bitbucket_checkpoints, fetch_bitbucket_releases
from .github_fetch import fetch_github_checkpoints, fetch_github_releases
from .gitlab_fetch import fetch_gitlab_checkpoints, fetch_gitlab_releases
from .scm_common import bitbucket_repo_from_remote, github_repo_from_remote, gitlab_project_from_remote

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(token\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(secret\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"https?://[^/\s:@]+:[^@\s/]+@"),
    re.compile(r"\b(ghp|github_pat|glpat|sk)-?[A-Za-z0-9_]{8,}\b"),
]


@dataclass(slots=True)
class DeliverySourceFetchOutcome:
    provider: str
    repository_name: str
    source_kind: str
    items: list[dict[str, Any]]
    failure: dict[str, Any] | None = None

    @property
    def failed(self) -> bool:
        return self.failure is not None


async def fetch_delivery_source_items_with_status(
    db: AsyncSession,
    *,
    repo: CodeRepository,
    source_kind: str,
    limit_per_repository: int,
    allowed_providers: set[str],
) -> DeliverySourceFetchOutcome:
    provider = str(repo.provider or "").strip().lower()
    repository_name = str(repo.name or repo.id or "")
    if provider not in allowed_providers:
        return DeliverySourceFetchOutcome(
            provider=provider,
            repository_name=repository_name,
            source_kind=source_kind,
            items=[],
        )
    provider_fetchers = {"github": _fetch_github, "bitbucket": _fetch_bitbucket, "gitlab": _fetch_gitlab}
    try:
        fetcher = provider_fetchers.get(provider)
        if fetcher is not None:
            outcome = await fetcher(db, repo, repository_name, source_kind, limit_per_repository)
            if outcome is not None:
                return outcome
    except Exception as exc:
        return _failed_outcome(
            provider=provider,
            repository_name=repository_name,
            source_kind=source_kind,
            category=_classify_provider_failure(exc),
            retryable=_is_retryable_provider_failure(exc),
            error=error_text("delivery_source_fetch_failed", exc),
        )
    return _failed_outcome(
        provider=provider,
        repository_name=repository_name,
        source_kind=source_kind,
        category="unsupported_source_kind",
        retryable=False,
        error=f"Unsupported design delivery source kind: {source_kind}",
    )


def _remote_config_failed(
    provider: str, repository_name: str, source_kind: str, label: str
) -> DeliverySourceFetchOutcome:
    return _failed_outcome(
        provider=provider,
        repository_name=repository_name,
        source_kind=source_kind,
        category="repository_config_failed",
        retryable=False,
        error=f"{label} repository remote URL is missing or unsupported.",
    )


# The provider fetchers below look the fetch functions up in this module's globals at call time: the service binds
# per-call overrides onto this module, and tests monkeypatch them there. ``None`` means the source kind is unknown.
async def _fetch_github(
    db: AsyncSession, repo: CodeRepository, repository_name: str, source_kind: str, limit: int
) -> DeliverySourceFetchOutcome | None:
    provider = "github"
    parsed = github_repo_from_remote(str(repo.remote_url or ""))
    if not parsed:
        return _remote_config_failed(provider, repository_name, source_kind, "GitHub")
    owner, repo_name = parsed
    if source_kind == "release":
        items = await fetch_github_releases(db, owner=owner, repo=repo_name, limit=limit)
        return _ok_outcome(provider, repository_name, source_kind, items)
    if source_kind == "checkpoint":
        items = await fetch_github_checkpoints(db, owner=owner, repo=repo_name, limit=limit)
        return _ok_outcome(provider, repository_name, source_kind, items)
    return None


async def _fetch_bitbucket(
    db: AsyncSession, repo: CodeRepository, repository_name: str, source_kind: str, limit: int
) -> DeliverySourceFetchOutcome | None:
    provider = "bitbucket"
    parsed = bitbucket_repo_from_remote(str(repo.remote_url or ""))
    if not parsed:
        return _remote_config_failed(provider, repository_name, source_kind, "Bitbucket")
    project_key, repo_slug = parsed
    if source_kind == "release":
        items = await fetch_bitbucket_releases(db, project_key=project_key, repo_slug=repo_slug, limit=limit)
        return _ok_outcome(provider, repository_name, source_kind, items)
    if source_kind == "checkpoint":
        items = await fetch_bitbucket_checkpoints(db, project_key=project_key, repo_slug=repo_slug, limit=limit)
        return _ok_outcome(provider, repository_name, source_kind, items)
    return None


async def _fetch_gitlab(
    db: AsyncSession, repo: CodeRepository, repository_name: str, source_kind: str, limit: int
) -> DeliverySourceFetchOutcome | None:
    provider = "gitlab"
    project_path = gitlab_project_from_remote(str(repo.remote_url or ""))
    if not project_path:
        return _remote_config_failed(provider, repository_name, source_kind, "GitLab")
    encoded = quote(project_path, safe="")
    if source_kind == "release":
        items = await fetch_gitlab_releases(db, project_path=encoded, limit=limit)
        return _ok_outcome(provider, repository_name, source_kind, items)
    if source_kind == "checkpoint":
        items = await fetch_gitlab_checkpoints(db, project_path=encoded, limit=limit)
        return _ok_outcome(provider, repository_name, source_kind, items)
    return None


def _ok_outcome(
    provider: str,
    repository_name: str,
    source_kind: str,
    items: list[dict[str, Any]],
) -> DeliverySourceFetchOutcome:
    return DeliverySourceFetchOutcome(
        provider=provider,
        repository_name=repository_name,
        source_kind=source_kind,
        items=list(items or []),
    )


def _failed_outcome(
    *,
    provider: str,
    repository_name: str,
    source_kind: str,
    category: str,
    retryable: bool,
    error: str,
) -> DeliverySourceFetchOutcome:
    return DeliverySourceFetchOutcome(
        provider=provider,
        repository_name=repository_name,
        source_kind=source_kind,
        items=[],
        failure={
            "provider": provider,
            "repository_name": repository_name,
            "source_kind": source_kind,
            "category": category,
            "retryable": bool(retryable),
            "error": sanitize_delivery_source_error(error),
        },
    )


def _classify_provider_failure(exc: Exception) -> str:
    text = str(exc).lower()
    if any(
        marker in text
        for marker in ["401", "403", "authorization", "unauthorized", "forbidden", "invalid token", "permission"]
    ):
        return "provider_auth_failed"
    if any(marker in text for marker in ["404", "not found", "unknown repository", "repository not found"]):
        return "provider_config_failed"
    if any(marker in text for marker in ["429", "rate limit", "timeout", "temporarily", "503", "502", "500"]):
        return "provider_retryable_failure"
    return "provider_fetch_failed"


def _is_retryable_provider_failure(exc: Exception) -> bool:
    return _classify_provider_failure(exc) in {"provider_retryable_failure", "provider_fetch_failed"}


def sanitize_delivery_source_error(value: str, *, max_length: int = 500) -> str:
    sanitized = " ".join(str(value or "").replace("\n", " ").replace("\r", " ").split())
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("https?://"):
            sanitized = pattern.sub("https://[redacted]@", sanitized)
        else:
            sanitized = pattern.sub(_redacted_match, sanitized)
    if len(sanitized) > max_length:
        return f"{sanitized[: max_length - 3]}..."
    return sanitized


def _redacted_match(match: re.Match[str]) -> str:
    return f"{match.group(1)}[redacted]" if match.groups() else "[redacted]"
