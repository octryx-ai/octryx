"""Exportable Engineering Knowledge Pack manifest helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)


def _quality_inputs(
    sources: list[EngineeringKnowledgePackSource],
    items: list[EngineeringKnowledgePackItem],
    target_versions: dict[str, Any],
    evidence_ledger: list[dict[str, Any]],
    coverage_matrix: dict[str, Any],
    coding_agent_evaluation: dict[str, Any],
    adversarial_review: dict[str, Any],
) -> dict[str, Any]:
    return {
        **_source_quality_inputs(sources),
        "target_version_exactness": _target_version_exactness(sources, target_versions),
        "citation_complete_count": sum(
            1 for source in sources if source.title and source.source_uri and source.checksum
        ),
        **_item_quality_inputs(items),
        "evidence_fact_count": len(evidence_ledger),
        "coverage_matrix_passed": bool(coverage_matrix.get("passed")),
        "coverage_missing_areas": list(coverage_matrix.get("missing_areas") or []),
        "coverage_covered_area_count": int(coverage_matrix.get("covered_area_count") or 0),
        "coding_agent_evaluation_status": str(coding_agent_evaluation.get("status") or ""),
        "coding_agent_evaluation_blockers": list(coding_agent_evaluation.get("blockers") or []),
        "adversarial_review_status": str(adversarial_review.get("status") or ""),
        "adversarial_review_blockers": list(adversarial_review.get("blockers") or []),
    }


def _source_quality_inputs(sources: list[EngineeringKnowledgePackSource]) -> dict[str, Any]:
    trust_counts = Counter(source.trust_tier for source in sources)
    type_counts = Counter(source.source_type for source in sources)
    audit_counts = Counter(
        str(dict(source.source_metadata or {}).get("source_audit", {}).get("status") or "missing")
        for source in sources
    )
    return {
        "source_count": len(sources),
        "trust_tier_counts": dict(trust_counts),
        "source_type_counts": dict(type_counts),
        "source_audit_counts": dict(audit_counts),
        "source_audit_complete_count": sum(
            1
            for source in sources
            if str(dict(source.source_metadata or {}).get("source_audit", {}).get("status") or "")
            in {"accepted", "limited"}
        ),
        "official_source_count": trust_counts.get("official", 0),
    }


def _target_version_exactness(
    sources: list[EngineeringKnowledgePackSource], target_versions: dict[str, Any]
) -> dict[str, bool]:
    exact_targets: dict[str, bool] = {}
    for coordinate, version in target_versions.items():
        expected = str(version or "").strip()
        exact_targets[str(coordinate)] = bool(
            expected
            and any(
                source.version_label == expected or source.source_metadata.get("target_version") == expected
                for source in sources
            )
        )
    return exact_targets


def _item_quality_inputs(items: list[EngineeringKnowledgePackItem]) -> dict[str, Any]:
    return {
        "item_count": len(items),
        "item_evidence_complete_count": sum(
            1 for item in items if item.source_id and item.item_metadata.get("evidence")
        ),
        "item_evidence_fact_complete_count": sum(
            1 for item in items if item.item_metadata.get("evidence_fact_ids")
        ),
        "item_metadata_complete_count": sum(
            1
            for item in items
            if item.title
            and item.summary
            and item.tags
            and item.version_scope
            and item.retrieval_priority
                and item.retrieval_rank is not None
        ),
    }


async def export_engineering_knowledge_manifest(
    db: AsyncSession,
    *,
    pack_version: EngineeringKnowledgePackVersion,
) -> dict[str, Any]:
    """Return a portable manifest that is sufficient to rehydrate a pack bundle."""

    sources, items = await _load_sources_and_items(db, pack_version_id=pack_version.id)
    pack = await db.get(EngineeringKnowledgePack, pack_version.pack_id)
    source_key_by_id = {source.id: source.source_key for source in sources}
    existing_manifest = dict(pack_version.manifest or {})
    evidence_ledger = list(existing_manifest.get("evidence_ledger") or [])
    coverage_matrix = dict(existing_manifest.get("coverage_matrix") or {})
    coding_agent_evaluation = dict(existing_manifest.get("coding_agent_evaluation") or {})
    adversarial_review = dict(existing_manifest.get("adversarial_review") or {})
    quality_inputs = _quality_inputs(
        list(sources),
        list(items),
        pack_version.target_versions or {},
        evidence_ledger,
        coverage_matrix,
        coding_agent_evaluation,
        adversarial_review,
    )
    return {
        "schema_version": 2,
        "manifest_kind": "engineering_knowledge_pack",
        "pack": _pack_manifest(pack),
        "pack_version_id": pack_version.id,
        "pack_id": pack_version.pack_id,
        "version": int(pack_version.version or 0),
        "status": pack_version.status,
        "quality_status": pack_version.quality_status,
        "archive_root": pack_version.archive_root,
        "source_versions": dict(pack_version.source_versions or {}),
        "target_versions": dict(pack_version.target_versions or {}),
        "compatibility_facts": dict(pack_version.compatibility_facts or {}),
        "sources": [_source_manifest(source) for source in sources],
        "items": [_item_manifest(item, source_key_by_id=source_key_by_id) for item in items],
        "evidence_ledger": evidence_ledger,
        "coverage_matrix": coverage_matrix,
        "coding_agent_evaluation": coding_agent_evaluation,
        "adversarial_review": adversarial_review,
        "quality_inputs": quality_inputs,
        "export": {
            "format": "engineering_knowledge_pack_manifest_v2",
            "export_ready": _is_export_ready(sources, quality_inputs),
            "contains_archive_paths": True,
            "requires_archive_root": bool(pack_version.archive_root),
        },
    }


async def _load_sources_and_items(
    db: AsyncSession, *, pack_version_id: str
) -> tuple[list[EngineeringKnowledgePackSource], list[EngineeringKnowledgePackItem]]:
    sources = (
        await db.execute(
            select(EngineeringKnowledgePackSource)
            .where(EngineeringKnowledgePackSource.pack_version_id == pack_version_id)
            .order_by(EngineeringKnowledgePackSource.source_key.asc())
        )
    ).scalars().all()
    items = (
        await db.execute(
            select(EngineeringKnowledgePackItem)
            .where(EngineeringKnowledgePackItem.pack_version_id == pack_version_id)
            .order_by(EngineeringKnowledgePackItem.retrieval_rank.asc(), EngineeringKnowledgePackItem.item_key.asc())
        )
    ).scalars().all()
    return sources, items


def _pack_manifest(pack: EngineeringKnowledgePack | None) -> dict[str, Any]:
    if pack is None:
        return {}
    return {
        "id": pack.id,
        "key": pack.key,
        "name": pack.name,
        "description": pack.description or "",
        "stack_key": pack.stack_key,
        "lifecycle_status": pack.lifecycle_status,
        "source_policy": dict(pack.source_policy or {}),
        "freshness_policy": dict(pack.freshness_policy or {}),
        "retrieval_policy": dict(pack.retrieval_policy or {}),
        "resolution_policy": dict(pack.resolution_policy or {}),
        "toolchain_policy": dict(pack.toolchain_policy or {}),
    }


def _source_manifest(source: EngineeringKnowledgePackSource) -> dict[str, Any]:
    metadata = dict(source.source_metadata or {})
    return {
        "source_key": source.source_key,
        "title": source.title,
        "source_uri": source.source_uri,
        "source_type": source.source_type,
        "trust_tier": source.trust_tier,
        "version_label": source.version_label,
        "checksum": source.checksum,
        "fetch_status": source.fetch_status,
        "freshness_status": source.freshness_status,
        "raw_archive_path": source.raw_archive_path,
        "parsed_archive_path": source.parsed_archive_path,
        "evidence_archive_path": source.evidence_archive_path,
        "metadata": metadata,
        "source_audit": dict(metadata.get("source_audit") or {}),
    }


def _item_manifest(item: EngineeringKnowledgePackItem, *, source_key_by_id: dict[str, str]) -> dict[str, Any]:
    return {
        "item_key": item.item_key,
        "source_key": source_key_by_id.get(str(item.source_id or "")),
        "title": item.title,
        "summary": item.summary or "",
        "tags": list(item.tags or []),
        "triggers": list(item.triggers or []),
        "version_scope": dict(item.version_scope or {}),
        "retrieval_priority": item.retrieval_priority,
        "retrieval_rank": int(item.retrieval_rank or 0),
        "metadata": dict(item.item_metadata or {}),
    }


def _is_export_ready(sources: list[EngineeringKnowledgePackSource], quality_inputs: dict[str, Any]) -> bool:
    exactness = dict(quality_inputs.get("target_version_exactness") or {})
    has_required_archive_paths = all(
        source.checksum and source.raw_archive_path and source.parsed_archive_path and source.evidence_archive_path
        for source in sources
    )
    return bool(sources) and has_required_archive_paths and all(exactness.values())
