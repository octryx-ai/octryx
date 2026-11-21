"""Filters and bounded summaries used by the Engineering Knowledge Pack search tools."""

from __future__ import annotations

from typing import Any

from ...models import (
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
    EngineeringKnowledgeRetrievalIndex,
)


def _clean_versions(value: dict[str, str] | None) -> dict[str, str]:
    return {str(key): str(version) for key, version in dict(value or {}).items() if str(version).strip()}


def _normalize_filter(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "all", "any", "*"}:
        return ""
    if normalized == "quality_passed":
        return ""
    return normalized


def _versions_include(actual: Any, expected: dict[str, str]) -> bool:
    actual_versions = {str(key): str(value) for key, value in dict(actual or {}).items()}
    return all(actual_versions.get(key) == version for key, version in expected.items())


def _record_matches_terms(record: EngineeringKnowledgeRetrievalIndex, terms: list[str]) -> bool:
    if not terms:
        return True
    haystack = str(record.search_text or "").lower()
    return all(term in haystack for term in terms)


def _retrieval_record_summary(record: EngineeringKnowledgeRetrievalIndex) -> dict[str, Any]:
    metadata = dict(record.record_metadata or {})
    return {
        "record_id": record.id,
        "record_kind": record.record_kind,
        "record_key": record.record_key,
        "title": record.title,
        "summary": str(record.summary or "")[:1000],
        "content": str(record.content or "")[:2000],
        "pack_id": record.pack_id,
        "pack_version_id": record.pack_version_id,
        "stack_key": record.stack_key,
        "source_versions": dict(record.source_versions or {}),
        "target_versions": dict(record.target_versions or {}),
        "coverage_areas": list(record.coverage_areas or []),
        "tags": list(record.tags or []),
        "triggers": list(record.triggers or []),
        "source_key": record.source_key,
        "source_uri": record.source_uri,
        "source_type": record.source_type,
        "trust_tier": record.trust_tier,
        "freshness_status": record.freshness_status,
        "archive_path": record.archive_path,
        "canonical_uri": record.canonical_uri,
        "fact_id": record.record_key if record.record_kind == "fact" else metadata.get("fact_id"),
        "metadata": metadata,
    }


def _version_has_trust_tier(version: EngineeringKnowledgePackVersion, trust_tier: str) -> bool:
    normalized = str(trust_tier or "").strip()
    if not normalized:
        return True
    if any(source.trust_tier == normalized for source in version.sources):
        return True
    return any(dict(item.item_metadata or {}).get("trust_tier") == normalized for item in version.items)


def _matching_items(items: list[EngineeringKnowledgePackItem], query_text: str) -> list[EngineeringKnowledgePackItem]:
    sorted_items = sorted(items, key=lambda item: (item.retrieval_rank, item.title))
    if not query_text:
        return sorted_items[:5]
    terms = [term for term in query_text.split() if term]
    matches: list[EngineeringKnowledgePackItem] = []
    for item in sorted_items:
        haystack = " ".join(
            [
                item.title or "",
                item.summary or "",
                item.content or "",
                " ".join(str(tag) for tag in item.tags or []),
                " ".join(str(trigger) for trigger in item.triggers or []),
            ]
        ).lower()
        if all(term in haystack for term in terms):
            matches.append(item)
    return matches[:5]


def _version_summary(
    version: EngineeringKnowledgePackVersion,
    *,
    matching_items: list[EngineeringKnowledgePackItem],
    include_match_items: bool,
) -> dict[str, Any]:
    pack = version.pack
    source_trust_tiers = sorted({source.trust_tier for source in version.sources})
    result = {
        "pack_id": version.pack_id,
        "pack_key": pack.key if pack else "",
        "pack_name": pack.name if pack else "",
        "stack_key": pack.stack_key if pack else "",
        "pack_version_id": version.id,
        "version": version.version,
        "status": version.status,
        "quality_status": version.quality_status,
        "source_versions": dict(version.source_versions or {}),
        "target_versions": dict(version.target_versions or {}),
        "source_count": len(version.sources),
        "item_count": len(version.items),
        "trust_tiers": source_trust_tiers,
        "quality_blockers": list((version.quality_report or {}).get("blockers") or []),
    }
    if include_match_items:
        result["matching_items"] = [_item_summary(item) for item in matching_items]
    return result


def _version_detail(
    version: EngineeringKnowledgePackVersion,
    *,
    include_items: bool,
    include_sources: bool,
    max_items: int,
) -> dict[str, Any]:
    summary = _version_summary(version, matching_items=[], include_match_items=False)
    summary["quality_report"] = dict(version.quality_report or {})
    summary["compatibility_facts"] = dict(version.compatibility_facts or {})
    if include_sources:
        summary["sources"] = [_source_summary(source) for source in version.sources]
    if include_items:
        sorted_items = sorted(version.items, key=lambda item: (item.retrieval_rank, item.title))
        summary["items"] = [_item_detail(item) for item in sorted_items[: max(1, min(int(max_items or 12), 50))]]
    return summary


def _source_summary(source: EngineeringKnowledgePackSource) -> dict[str, Any]:
    return {
        "source_id": source.id,
        "source_key": source.source_key,
        "title": source.title,
        "source_uri": source.source_uri,
        "source_type": source.source_type,
        "trust_tier": source.trust_tier,
        "version_label": source.version_label,
        "fetch_status": source.fetch_status,
        "freshness_status": source.freshness_status,
        "checksum": source.checksum,
        "evidence_archive_path": source.evidence_archive_path,
    }


def _item_summary(item: EngineeringKnowledgePackItem) -> dict[str, Any]:
    return {
        "item_id": item.id,
        "item_key": item.item_key,
        "title": item.title,
        "summary": item.summary,
        "tags": list(item.tags or []),
        "retrieval_rank": item.retrieval_rank,
        "source_key": item.source.source_key if item.source else None,
    }


def _item_detail(item: EngineeringKnowledgePackItem) -> dict[str, Any]:
    detail = _item_summary(item)
    detail["content"] = str(item.content or "")[:5000]
    detail["version_scope"] = dict(item.version_scope or {})
    detail["metadata"] = dict(item.item_metadata or {})
    return detail
