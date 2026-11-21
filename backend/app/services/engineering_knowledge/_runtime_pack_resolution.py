"""Pack assignment, freshness, and retrieval helpers for runtime resolution."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    CodeRepository,
    EngineeringKnowledgePack,
    EngineeringKnowledgePackAssignment,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackVersion,
    EngineeringKnowledgeRetrievalIndex,
)
from ._runtime_repository_resolution import repository_identifiers, slug
from ._runtime_types import (
    EngineeringKnowledgeRuntimeRequest,
    EngineeringKnowledgeRuntimeResolution,
    PackResolution,
)


async def resolve_runtime_pack(
    db: AsyncSession,
    *,
    request: EngineeringKnowledgeRuntimeRequest,
    repository: CodeRepository,
    project_id: str | None,
) -> PackResolution:
    assignment = await find_matching_assignment(db, request=request, repository=repository, project_id=project_id)
    if assignment and version_matches_targets(assignment.pack_version, request.target_versions):
        return PackResolution(
            pack=assignment.pack_version.pack,
            pack_version=assignment.pack_version,
            assignment=assignment,
            match_reason=f"{assignment.scope_type} assignment",
        )

    stmt = (
        select(EngineeringKnowledgePackVersion)
        .join(EngineeringKnowledgePack, EngineeringKnowledgePackVersion.pack_id == EngineeringKnowledgePack.id)
        .options(
            selectinload(EngineeringKnowledgePackVersion.pack),
            selectinload(EngineeringKnowledgePackVersion.sources),
            selectinload(EngineeringKnowledgePackVersion.items).selectinload(EngineeringKnowledgePackItem.source),
        )
        .where(
            EngineeringKnowledgePack.stack_key == request.stack_key,
            EngineeringKnowledgePack.is_active.is_(True),
            EngineeringKnowledgePack.lifecycle_status == "active",
            EngineeringKnowledgePackVersion.status == "published",
            EngineeringKnowledgePackVersion.quality_status == "passed",
        )
        .order_by(EngineeringKnowledgePackVersion.version.desc())
    )
    versions = (await db.execute(stmt)).scalars().unique().all()
    for version in versions:
        if version_matches_targets(version, request.target_versions):
            return PackResolution(version.pack, version, None, "published exact-version fallback")
    return PackResolution(None, None, None, "no exact-version published pack")


async def find_matching_assignment(
    db: AsyncSession,
    *,
    request: EngineeringKnowledgeRuntimeRequest,
    repository: CodeRepository,
    project_id: str | None,
) -> EngineeringKnowledgePackAssignment | None:
    stmt = (
        select(EngineeringKnowledgePackAssignment)
        .options(
            selectinload(EngineeringKnowledgePackAssignment.pack_version).selectinload(
                EngineeringKnowledgePackVersion.pack
            ),
            selectinload(EngineeringKnowledgePackAssignment.pack_version).selectinload(
                EngineeringKnowledgePackVersion.sources
            ),
            selectinload(EngineeringKnowledgePackAssignment.pack_version)
            .selectinload(EngineeringKnowledgePackVersion.items)
            .selectinload(EngineeringKnowledgePackItem.source),
        )
        .where(
            EngineeringKnowledgePackAssignment.assignment_status == "active",
            EngineeringKnowledgePackAssignment.stack_key == request.stack_key,
        )
        .order_by(
            EngineeringKnowledgePackAssignment.priority.asc(),
            EngineeringKnowledgePackAssignment.assigned_at.desc(),
        )
    )
    assignments = (await db.execute(stmt)).scalars().unique().all()
    scored = [
        (assignment_scope_score(assignment, repository=repository, project_id=project_id), assignment)
        for assignment in assignments
    ]
    for score, assignment in sorted((item for item in scored if item[0] >= 0), key=lambda item: item[0]):
        version = assignment.pack_version
        if version.status == "published" and version.quality_status == "passed":
            return assignment
    return None


def assignment_scope_score(
    assignment: EngineeringKnowledgePackAssignment,
    *,
    repository: CodeRepository,
    project_id: str | None,
) -> int:
    repo_identifiers = {slug(item) for item in repository_identifiers(repository)}
    if assignment.scope_type == "repository":
        if assignment.repository_id == repository.id or slug(assignment.scope_id) in repo_identifiers:
            return 0
        return -1
    if assignment.scope_type in {"workspace", "project"}:
        workspace_match = assignment.workspace_id and assignment.workspace_id == (project_id or repository.project_id)
        scope_match = assignment.scope_id and assignment.scope_id in {project_id, repository.project_id}
        return 10 if workspace_match or scope_match else -1
    if assignment.scope_type == "global":
        return 30
    return -1


def version_matches_targets(version: EngineeringKnowledgePackVersion, target_versions: dict[str, str]) -> bool:
    version_targets = {str(key): str(value) for key, value in dict(version.target_versions or {}).items()}
    return bool(target_versions) and all(version_targets.get(key) == value for key, value in target_versions.items())


def evaluate_selected_pack(
    resolution: EngineeringKnowledgeRuntimeResolution,
    pack_version: EngineeringKnowledgePackVersion,
) -> None:
    stale_sources = [source.source_key for source in pack_version.sources if source.freshness_status == "stale"]
    if stale_sources:
        append_blocker(
            resolution,
            "stale_engineering_knowledge_pack",
            "Refresh stale pack sources before using this pack: " + ", ".join(sorted(stale_sources)),
        )
    freshness_counts = Counter(source.freshness_status or "unknown" for source in pack_version.sources)
    resolution.source_freshness_counts = dict(freshness_counts)
    metadata_only = [source.source_key for source in pack_version.sources if source.fetch_status != "fetched"]
    if metadata_only:
        resolution.warnings.append(
            {
                "code": "pack_sources_not_fully_archived",
                "message": "Some selected pack sources are not fully archived: " + ", ".join(sorted(metadata_only)),
            }
        )


def attach_retrieved_items(
    resolution: EngineeringKnowledgeRuntimeResolution,
    pack_version: EngineeringKnowledgePackVersion,
    *,
    max_items: int,
    budget_tokens: int,
) -> None:
    budget_chars = max(800, int(budget_tokens or 0) * 4)
    remaining = budget_chars
    items: list[dict[str, Any]] = []
    source_ids: list[str] = []
    sorted_items = sorted(pack_version.items, key=lambda item: (item.retrieval_rank, item.title))
    for item in sorted_items[: max(1, max_items)]:
        if remaining <= 0:
            break
        content = str(item.content or item.summary or "")
        trimmed = content[: min(len(content), remaining, 5_000)]
        source = item.source
        items.append(
            {
                "item_id": item.id,
                "title": item.title,
                "summary": item.summary,
                "content": trimmed,
                "tags": list(item.tags or []),
                "retrieval_rank": item.retrieval_rank,
                "source_id": source.id if source else None,
                "source_key": source.source_key if source else None,
            }
        )
        remaining -= len(trimmed)
        if source and source.id not in source_ids:
            source_ids.append(source.id)
    resolution.items = items
    resolution.source_ids = source_ids


async def attach_retrieved_index_records(
    db: AsyncSession,
    resolution: EngineeringKnowledgeRuntimeResolution,
    pack_version: EngineeringKnowledgePackVersion,
    *,
    max_records_per_kind: int,
) -> None:
    """The pack's index records in their stored order (kind, title); the prompt does not rank them."""
    records = (
        await db.execute(
            select(EngineeringKnowledgeRetrievalIndex)
            .where(
                EngineeringKnowledgeRetrievalIndex.pack_version_id == pack_version.id,
                EngineeringKnowledgeRetrievalIndex.is_active.is_(True),
                EngineeringKnowledgeRetrievalIndex.record_kind.in_(["item", "fact", "source"]),
            )
            .order_by(
                EngineeringKnowledgeRetrievalIndex.record_kind.asc(),
                EngineeringKnowledgeRetrievalIndex.title.asc(),
            )
        )
    ).scalars().all()
    grouped: dict[str, list[dict[str, Any]]] = {"items": [], "facts": [], "sources": []}
    for record in records:
        bucket = {"item": "items", "fact": "facts", "source": "sources"}.get(record.record_kind)
        if not bucket or len(grouped[bucket]) >= max(1, max_records_per_kind):
            continue
        grouped[bucket].append(_runtime_record(record))
    resolution.engineering_pack_retrieval = grouped


def append_blocker(
    resolution: EngineeringKnowledgeRuntimeResolution,
    code: str,
    message: str,
) -> None:
    if code not in {blocker.get("code") for blocker in resolution.blockers}:
        resolution.blockers.append({"code": code, "message": message})


def _runtime_record(record: EngineeringKnowledgeRetrievalIndex) -> dict[str, Any]:
    metadata = dict(record.record_metadata or {})
    return {
        "record_kind": record.record_kind,
        "record_key": record.record_key,
        "title": record.title,
        "summary": str(record.summary or "")[:800],
        "content": str(record.content or "")[:1200],
        "source_key": record.source_key,
        "source_uri": record.source_uri,
        "canonical_uri": record.canonical_uri,
        "archive_path": record.archive_path,
        "coverage_areas": list(record.coverage_areas or []),
        "trust_tier": record.trust_tier,
        "freshness_status": record.freshness_status,
        "fact_id": record.record_key if record.record_kind == "fact" else metadata.get("fact_id"),
    }
