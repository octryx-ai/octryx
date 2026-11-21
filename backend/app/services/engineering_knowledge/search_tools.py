"""Search and bounded retrieval helpers for Engineering Knowledge Packs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackVersion,
    EngineeringKnowledgeRetrievalIndex,
)
from ._runtime_types import EngineeringUpgradeTarget
from .runtime_prompt import build_engineering_runtime_request
from .search_tools_views import (
    _clean_versions,
    _matching_items,
    _normalize_filter,
    _record_matches_terms,
    _retrieval_record_summary,
    _version_detail,
    _version_has_trust_tier,
    _version_summary,
    _versions_include,
)

__all__ = [
    "get_engineering_knowledge_pack_detail",
    "resolve_engineering_knowledge_pack_for_task",
    "search_engineering_knowledge_packs",
    "search_engineering_knowledge_retrieval_index",
]


async def search_engineering_knowledge_packs(
    db: AsyncSession,
    *,
    stack_key: str = "",
    source_versions: dict[str, str] | None = None,
    target_versions: dict[str, str] | None = None,
    topic: str = "",
    artifact: str = "",
    trust_tier: str = "",
    status: str = "published",
    quality_status: str = "passed",
    limit: int = 10,
) -> dict[str, Any]:
    """Search Engineering Packs with version-aware filtering."""
    versions = await _load_candidate_versions(db, stack_key=stack_key)
    query_text = " ".join(part for part in [topic, artifact] if part).strip().lower()
    source_filter = _clean_versions(source_versions)
    target_filter = _clean_versions(target_versions)
    status_filter = _normalize_filter(status)
    quality_filter = _normalize_filter(quality_status)
    max_results = max(1, min(int(limit or 10), 50))

    results: list[dict[str, Any]] = []
    for version in versions:
        pack = version.pack
        if pack is None or not pack.is_active or pack.lifecycle_status != "active":
            continue
        if status_filter and version.status != status_filter:
            continue
        if quality_filter and version.quality_status != quality_filter:
            continue
        if source_filter and not _versions_include(version.source_versions, source_filter):
            continue
        if target_filter and not _versions_include(version.target_versions, target_filter):
            continue
        if trust_tier and not _version_has_trust_tier(version, trust_tier):
            continue
        matching_items = _matching_items(version.items, query_text)
        if query_text and not matching_items:
            continue
        results.append(
            _version_summary(
                version,
                matching_items=matching_items,
                include_match_items=bool(query_text),
            )
        )
        if len(results) >= max_results:
            break

    return {"status": "ok", "count": len(results), "packs": results}


async def get_engineering_knowledge_pack_detail(
    db: AsyncSession,
    *,
    pack_key: str = "",
    pack_version_id: str = "",
    include_items: bool = True,
    include_sources: bool = True,
    max_items: int = 12,
) -> dict[str, Any]:
    """Return bounded details for one Engineering Pack version."""
    version = await _find_version(db, pack_key=pack_key, pack_version_id=pack_version_id)
    if version is None:
        return {"error": "Engineering Knowledge Pack version not found"}
    return {
        "status": "ok",
        "pack": _version_detail(
            version,
            include_items=include_items,
            include_sources=include_sources,
            max_items=max_items,
        ),
    }


async def resolve_engineering_knowledge_pack_for_task(
    db: AsyncSession,
    *,
    target: EngineeringUpgradeTarget | None,
    max_items: int = 8,
) -> dict[str, Any]:
    """Resolve the best published Engineering Pack for an explicit migration target."""
    if target is None:
        return {
            "status": "not_specified",
            "blockers": [
                {
                    "code": "target_not_specified",
                    "message": "Pass stack_key and exact target_versions; versions are not read from prompt text.",
                }
            ],
            "pack": None,
        }
    request = build_engineering_runtime_request(target=target)
    if request.blockers:
        return {"status": "blocked", "blockers": request.blockers, "pack": None}
    search = await search_engineering_knowledge_packs(
        db,
        stack_key=request.stack_key,
        source_versions=request.source_versions,
        target_versions=request.target_versions,
        status="published",
        quality_status="passed",
        limit=1,
    )
    if not search["packs"]:
        return {
            "status": "blocked",
            "blockers": [
                {
                    "code": "missing_engineering_knowledge_pack",
                    "message": "No published quality-passed Engineering Pack matched the requested exact versions.",
                }
            ],
            "pack": None,
        }
    pack_version_id = str(search["packs"][0]["pack_version_id"])
    return await get_engineering_knowledge_pack_detail(
        db,
        pack_version_id=pack_version_id,
        include_items=True,
        include_sources=True,
        max_items=max_items,
    )


async def search_engineering_knowledge_retrieval_index(
    db: AsyncSession,
    *,
    query: str = "",
    pack_version_id: str = "",
    stack_key: str = "",
    source_versions: dict[str, str] | None = None,
    target_versions: dict[str, str] | None = None,
    record_kind: str = "",
    coverage_area: str = "",
    trust_tier: str = "",
    source_type: str = "",
    freshness_status: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Search active published Engineering Pack retrieval records."""
    max_results = max(1, min(int(limit or 10), 50))
    stmt = (
        select(EngineeringKnowledgeRetrievalIndex)
        .where(EngineeringKnowledgeRetrievalIndex.is_active.is_(True))
        .order_by(
            EngineeringKnowledgeRetrievalIndex.record_kind.asc(),
            EngineeringKnowledgeRetrievalIndex.title.asc(),
        )
        .limit(500)
    )
    if stack_key:
        stmt = stmt.where(EngineeringKnowledgeRetrievalIndex.stack_key == stack_key)
    if pack_version_id:
        stmt = stmt.where(EngineeringKnowledgeRetrievalIndex.pack_version_id == pack_version_id)
    normalized_kind = _normalize_filter(record_kind)
    if normalized_kind:
        stmt = stmt.where(EngineeringKnowledgeRetrievalIndex.record_kind == normalized_kind)
    if trust_tier:
        stmt = stmt.where(EngineeringKnowledgeRetrievalIndex.trust_tier == trust_tier)
    if source_type:
        stmt = stmt.where(EngineeringKnowledgeRetrievalIndex.source_type == source_type)
    if freshness_status:
        stmt = stmt.where(EngineeringKnowledgeRetrievalIndex.freshness_status == freshness_status)

    source_filter = _clean_versions(source_versions)
    target_filter = _clean_versions(target_versions)
    terms = [term for term in str(query or "").lower().split() if term]
    coverage_filter = str(coverage_area or "").strip()
    records = (await db.execute(stmt)).scalars().all()
    matches = [
        record
        for record in records
        if _versions_include(record.source_versions, source_filter)
        and _versions_include(record.target_versions, target_filter)
        and (not coverage_filter or coverage_filter in set(record.coverage_areas or []))
        and _record_matches_terms(record, terms)
    ][:max_results]
    return {
        "status": "ok",
        "count": len(matches),
        "records": [_retrieval_record_summary(record) for record in matches],
    }


async def _load_candidate_versions(db: AsyncSession, *, stack_key: str) -> list[EngineeringKnowledgePackVersion]:
    stmt = (
        select(EngineeringKnowledgePackVersion)
        .join(EngineeringKnowledgePack, EngineeringKnowledgePackVersion.pack_id == EngineeringKnowledgePack.id)
        .options(
            selectinload(EngineeringKnowledgePackVersion.pack),
            selectinload(EngineeringKnowledgePackVersion.sources),
            selectinload(EngineeringKnowledgePackVersion.items).selectinload(EngineeringKnowledgePackItem.source),
        )
        .order_by(EngineeringKnowledgePackVersion.updated_at.desc(), EngineeringKnowledgePackVersion.version.desc())
    )
    if stack_key:
        stmt = stmt.where(EngineeringKnowledgePack.stack_key == stack_key)
    return (await db.execute(stmt)).scalars().unique().all()


async def _find_version(
    db: AsyncSession,
    *,
    pack_key: str,
    pack_version_id: str,
) -> EngineeringKnowledgePackVersion | None:
    stmt = (
        select(EngineeringKnowledgePackVersion)
        .join(EngineeringKnowledgePack, EngineeringKnowledgePackVersion.pack_id == EngineeringKnowledgePack.id)
        .options(
            selectinload(EngineeringKnowledgePackVersion.pack),
            selectinload(EngineeringKnowledgePackVersion.sources),
            selectinload(EngineeringKnowledgePackVersion.items).selectinload(EngineeringKnowledgePackItem.source),
        )
        .order_by(EngineeringKnowledgePackVersion.version.desc())
    )
    if pack_version_id:
        stmt = stmt.where(EngineeringKnowledgePackVersion.id == pack_version_id)
    elif pack_key:
        stmt = stmt.where(EngineeringKnowledgePack.key == pack_key)
    else:
        return None
    return (await db.execute(stmt)).scalars().unique().first()

