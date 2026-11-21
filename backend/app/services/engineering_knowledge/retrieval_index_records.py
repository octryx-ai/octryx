"""Retrieval index rows built from a published pack version: pack, source, item and fact records."""

from __future__ import annotations

import uuid
from typing import Any

from ...models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
    EngineeringKnowledgeRetrievalIndex,
)


def _new_record(
    *,
    pack: EngineeringKnowledgePack,
    version: EngineeringKnowledgePackVersion,
    record_kind: str,
    record_key: str,
    title: str,
    summary: str = "",
    content: str = "",
    coverage_areas: list[str] | None = None,
    tags: list[str] | None = None,
    triggers: list[str] | None = None,
    source: EngineeringKnowledgePackSource | None = None,
    source_key: str = "",
    source_uri: str = "",
    source_type: str = "",
    trust_tier: str = "",
    freshness_status: str = "",
    archive_path: str = "",
    canonical_uri: str = "",
    indexed_at,
    metadata: dict[str, Any] | None = None,
) -> EngineeringKnowledgeRetrievalIndex:
    return EngineeringKnowledgeRetrievalIndex(
        id=str(uuid.uuid4()),
        pack_id=pack.id,
        pack_version_id=version.id,
        record_kind=record_kind,
        record_key=record_key,
        title=title[:500],
        summary=summary,
        content=content,
        search_text=_search_text(
            title=title,
            summary=summary,
            content=content,
            tags=tags or [],
            triggers=triggers or [],
            coverage_areas=coverage_areas or [],
            source_key=source_key or (source.source_key if source else ""),
            source_uri=source_uri or (source.source_uri if source else ""),
        ),
        stack_key=pack.stack_key,
        source_versions=dict(version.source_versions or {}),
        target_versions=dict(version.target_versions or {}),
        coverage_areas=list(coverage_areas or []),
        tags=list(tags or []),
        triggers=list(triggers or []),
        source_id=source.id if source else None,
        source_key=source_key or (source.source_key if source else None),
        source_uri=source_uri or (source.source_uri if source else None),
        source_type=source_type or (source.source_type if source else None),
        trust_tier=trust_tier or (source.trust_tier if source else None),
        freshness_status=freshness_status or (source.freshness_status if source else None),
        archive_path=archive_path,
        canonical_uri=canonical_uri,
        record_metadata=dict(metadata or {}),
        is_active=True,
        indexed_at=indexed_at,
    )


def _source_record(
    pack: EngineeringKnowledgePack,
    version: EngineeringKnowledgePackVersion,
    source: EngineeringKnowledgePackSource,
    *,
    indexed_at,
) -> EngineeringKnowledgeRetrievalIndex:
    metadata = dict(source.source_metadata or {})
    source_audit = dict(metadata.get("source_audit") or {})
    content = " ".join(
        str(item)
        for item in [
            source.title,
            source.source_uri,
            source.source_type,
            source.trust_tier,
            source.version_label,
            source_audit.get("reason"),
        ]
        if item
    )
    return _new_record(
        pack=pack,
        version=version,
        record_kind="source",
        record_key=source.source_key,
        title=source.title,
        summary=str(source_audit.get("reason") or ""),
        content=content,
        coverage_areas=list(source_audit.get("coverage_areas") or []),
        source=source,
        archive_path=source.parsed_archive_path or source.raw_archive_path or "",
        canonical_uri=str(source_audit.get("canonical_uri") or source.source_uri),
        indexed_at=indexed_at,
        metadata={
            "source_audit": source_audit,
            "raw_archive_path": source.raw_archive_path,
            "parsed_archive_path": source.parsed_archive_path,
            "evidence_archive_path": source.evidence_archive_path,
            "checksum": source.checksum,
        },
    )


def _item_record(
    pack: EngineeringKnowledgePack,
    version: EngineeringKnowledgePackVersion,
    item: EngineeringKnowledgePackItem,
    *,
    indexed_at,
) -> EngineeringKnowledgeRetrievalIndex:
    metadata = dict(item.item_metadata or {})
    source = item.source
    source_metadata = dict(source.source_metadata or {}) if source else {}
    source_audit = dict(source_metadata.get("source_audit") or {})
    coverage_areas = sorted(
        {str(area) for fact in metadata.get("evidence") or [] for area in list(fact.get("coverage_areas") or [])}
    )
    return _new_record(
        pack=pack,
        version=version,
        record_kind="item",
        record_key=item.item_key,
        title=item.title,
        summary=item.summary or "",
        content=item.content or "",
        coverage_areas=coverage_areas,
        tags=list(item.tags or []),
        triggers=list(item.triggers or []),
        source=source,
        archive_path=str(
            metadata.get("archive_path")
            or (source.parsed_archive_path if source else "")
            or (source.raw_archive_path if source else "")
            or ""
        ),
        canonical_uri=str(source_audit.get("canonical_uri") or (source.source_uri if source else "")),
        indexed_at=indexed_at,
        metadata={
            "item_id": item.id,
            "retrieval_priority": item.retrieval_priority,
            "retrieval_rank": item.retrieval_rank,
            "version_scope": dict(item.version_scope or {}),
            "evidence_fact_ids": list(metadata.get("evidence_fact_ids") or []),
        },
    )


def _fact_record(
    pack: EngineeringKnowledgePack,
    version: EngineeringKnowledgePackVersion,
    fact: dict[str, Any],
    *,
    source: EngineeringKnowledgePackSource | None,
    indexed_at,
) -> EngineeringKnowledgeRetrievalIndex:
    fact_id = str(fact.get("fact_id") or "").strip() or str(uuid.uuid4())
    claim = str(fact.get("claim") or "").strip()
    source_uri = str(fact.get("source_uri") or "")
    return _new_record(
        pack=pack,
        version=version,
        record_kind="fact",
        record_key=fact_id,
        title=claim[:500] or fact_id,
        summary=claim,
        content=str(fact.get("excerpt") or claim),
        coverage_areas=[str(area) for area in list(fact.get("coverage_areas") or []) if str(area).strip()],
        source=source,
        source_key=str(fact.get("source_key") or ""),
        source_uri=source_uri,
        archive_path=str(fact.get("archive_path") or ""),
        canonical_uri=source_uri,
        indexed_at=indexed_at,
        metadata={key: value for key, value in fact.items() if key not in {"claim", "excerpt"}},
    )


def _pack_content(version: EngineeringKnowledgePackVersion) -> str:
    quality_report = dict(version.quality_report or {})
    compatibility_facts = dict(version.compatibility_facts or {})
    return "\n".join(
        [
            "Engineering Knowledge Pack",
            f"Source versions: {version.source_versions}",
            f"Target versions: {version.target_versions}",
            f"Quality status: {version.quality_status}",
            f"Quality passed: {quality_report.get('passed')}",
            f"Compatibility facts: {compatibility_facts}",
        ]
    )


def _search_text(
    *,
    title: str,
    summary: str,
    content: str,
    tags: list[str],
    triggers: list[str],
    coverage_areas: list[str],
    source_key: str,
    source_uri: str,
) -> str:
    return " ".join(
        str(part)
        for part in [
            title,
            summary,
            content,
            " ".join(tags),
            " ".join(triggers),
            " ".join(coverage_areas),
            source_key,
            source_uri,
        ]
        if part
    ).lower()
