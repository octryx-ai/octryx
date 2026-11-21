"""Shared steps of the trace sync runners: load the sync base, fetch per repository, link once, shape the result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.design_artifact.crud import create_design_trace_link, list_design_trace_links

from ...models import CodeRepository, DesignArtifact
from .fetch import fetch_delivery_source_items_with_status
from .workflows import ALLOWED_PROVIDERS

TEXT_RULES = ["artifact_titles", "artifact_summaries", "task_titles"]


async def load_sync_base(
    db: AsyncSession,
    *,
    project_id: str,
    providers: list[str] | None,
) -> tuple[list[CodeRepository], list[dict[str, Any]], set[tuple[str, str, str, str]]]:
    repositories = (
        (
            await db.execute(
                select(CodeRepository).where(
                    CodeRepository.project_id == project_id,
                    CodeRepository.is_active.is_(True),
                    CodeRepository.provider.in_(providers or ["github", "bitbucket"]),
                )
            )
        )
        .scalars()
        .all()
    )
    artifacts = (
        (
            await db.execute(
                select(DesignArtifact).where(
                    DesignArtifact.project_id == project_id,
                    DesignArtifact.status.in_(["approved", "review"]),
                )
            )
        )
        .scalars()
        .all()
    )
    artifact_payloads = [{"id": a.id, "title": a.title or "", "summary": a.summary or ""} for a in artifacts]
    existing_links = await list_design_trace_links(db, project_id=project_id)
    existing_keys = {
        (
            str(link.get("artifact_id") or ""),
            str(link.get("target_type") or ""),
            str(link.get("target_id") or ""),
            str(link.get("url") or ""),
        )
        for link in existing_links
    }
    return repositories, artifact_payloads, existing_keys


@dataclass
class SyncRun:
    """Running totals of one sync: scanned repositories, fetch failures, candidates and created links."""

    db: AsyncSession
    project_id: str
    mode: str
    limit_per_repository: int
    existing_keys: set[tuple[str, str, str, str]]
    created_links: list[dict[str, Any]] = field(default_factory=list)
    scanned_repositories: list[str] = field(default_factory=list)
    fetch_failures: list[dict[str, Any]] = field(default_factory=list)
    total_candidates: int = 0

    async def fetch(self, repo: CodeRepository, source_kind: str) -> tuple[str, list[dict[str, Any]]]:
        repo_name = str(repo.name or repo.id)
        fetch_outcome = await fetch_delivery_source_items_with_status(
            self.db,
            repo=repo,
            source_kind=source_kind,
            limit_per_repository=self.limit_per_repository,
            allowed_providers=ALLOWED_PROVIDERS,
        )
        items = fetch_outcome.items
        if fetch_outcome.failure:
            self.fetch_failures.append(fetch_outcome.failure)
        self.scanned_repositories.append(repo_name)
        self.total_candidates += len(items)
        return repo_name, items

    async def link(self, key: tuple[str, str, str, str], payload: dict[str, Any]) -> None:
        if key in self.existing_keys or self.mode == "suggest":
            return
        created = await create_design_trace_link(
            self.db, project_id=self.project_id, payload=payload, created_by_user_id=None
        )
        self.existing_keys.add(key)
        self.created_links.append(created)

    def result(self, active_rules: list[str]) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "repositories_scanned": self.scanned_repositories,
            "repositories_scanned_count": len(self.scanned_repositories),
            "candidate_count": self.total_candidates,
            "created_links": self.created_links,
            "created_count": len(self.created_links),
            "match_rules": active_rules,
            "fetch_failures": self.fetch_failures,
            "fetch_failure_count": len(self.fetch_failures),
            "status": "degraded" if self.fetch_failures else "completed",
        }
