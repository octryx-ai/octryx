"""Quality gate and compatibility facts computed from an exported pack manifest."""

from __future__ import annotations

from typing import Any


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _evaluate_manifest_quality(
    manifest: dict[str, Any],
    *,
    source_plan: dict[str, Any],
    source_policy: dict[str, Any],
) -> dict[str, Any]:
    sources = list(manifest.get("sources") or [])
    quality_inputs = dict(manifest.get("quality_inputs") or {})
    archived_count = sum(1 for source in sources if source.get("checksum") and source.get("fetch_status") == "fetched")
    planned_count = len(source_plan.get("sources") or [])
    min_archived_sources = int(source_policy.get("min_archived_sources") or planned_count or 1)
    # The blocker order is part of the report, so each group appends in the original sequence.
    blockers: list[dict[str, str]] = []
    blockers.extend(_source_coverage_blockers(sources, archived_count, min_archived_sources, source_policy))
    source_audit_counts = dict(quality_inputs.get("source_audit_counts") or {})
    if sources and not source_audit_counts:
        source_audit_counts = {"missing": len(sources)}
    blockers.extend(_source_audit_blockers(source_audit_counts))
    blockers.extend(_target_and_freshness_blockers(sources, quality_inputs))
    blockers.extend(_item_evidence_blockers(quality_inputs))
    blockers.extend(_evaluation_blockers(quality_inputs))
    blockers.extend(_item_metadata_blockers(quality_inputs))
    return _quality_report(
        quality_inputs,
        archived_count=archived_count,
        planned_count=planned_count,
        min_archived_sources=min_archived_sources,
        source_audit_counts=source_audit_counts,
        blockers=blockers,
    )


def _source_coverage_blockers(
    sources: list[dict[str, Any]],
    archived_count: int,
    min_archived_sources: int,
    source_policy: dict[str, Any],
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if archived_count < min_archived_sources:
        blockers.append(
            _blocker(
                "insufficient_archived_sources",
                f"Archived source coverage {archived_count}/{min_archived_sources} is below policy.",
            )
        )
    allowed_trust_tiers = {str(tier) for tier in source_policy.get("trust_tiers") or []}
    if allowed_trust_tiers:
        disallowed_trust_tiers = sorted(
            {
                str(source.get("trust_tier") or "")
                for source in sources
                if str(source.get("trust_tier") or "") not in allowed_trust_tiers
            }
        )
        if disallowed_trust_tiers:
            blockers.append(
                _blocker(
                    "disallowed_source_trust_tier",
                    "Sources use disallowed trust tiers: " + ", ".join(disallowed_trust_tiers),
                )
            )
    return blockers


def _source_audit_blockers(source_audit_counts: dict[str, Any]) -> list[dict[str, str]]:
    unaudited_count = int(source_audit_counts.get("missing") or 0)
    rejected_count = int(source_audit_counts.get("rejected") or 0)
    if not (unaudited_count or rejected_count):
        return []
    return [
        _blocker(
            "source_audit_not_passed",
            (
                "Source audit must be completed and accepted before review: "
                f"missing={unaudited_count}, rejected={rejected_count}."
            ),
        )
    ]


def _target_and_freshness_blockers(
    sources: list[dict[str, Any]],
    quality_inputs: dict[str, Any],
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    exactness = dict(quality_inputs.get("target_version_exactness") or {})
    missing_exact_targets = [coordinate for coordinate, is_exact in exactness.items() if not is_exact]
    if missing_exact_targets:
        blockers.append(
            _blocker(
                "missing_exact_target_version_sources",
                "Missing exact target-version evidence for: " + ", ".join(sorted(missing_exact_targets)),
            )
        )
    stale_sources = [source["source_key"] for source in sources if source.get("freshness_status") == "stale"]
    if stale_sources:
        blockers.append(
            _blocker(
                "stale_sources",
                "Stale sources must be refreshed before the pack can pass: " + ", ".join(stale_sources),
            )
        )
    return blockers


def _item_evidence_blockers(quality_inputs: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    item_count = int(quality_inputs.get("item_count") or 0)
    if item_count <= 0:
        blockers.append(
            _blocker(
                "missing_retrievable_items",
                "No retrievable Engineering Pack items were created from archived sources.",
            )
        )
    evidence_complete_count = int(quality_inputs.get("item_evidence_complete_count") or 0)
    if item_count > 0 and evidence_complete_count < item_count:
        blockers.append(
            _blocker(
                "missing_item_evidence",
                f"Item evidence coverage {evidence_complete_count}/{item_count} is incomplete.",
            )
        )
    evidence_fact_count = int(quality_inputs.get("evidence_fact_count") or 0)
    if evidence_fact_count <= 0:
        blockers.append(
            _blocker(
                "missing_evidence_ledger",
                "No source-backed Evidence Ledger facts were extracted from accepted sources.",
            )
        )
    evidence_fact_complete_count = int(quality_inputs.get("item_evidence_fact_complete_count") or 0)
    if item_count > 0 and evidence_fact_complete_count < item_count:
        blockers.append(
            _blocker(
                "missing_item_evidence_facts",
                f"Item Evidence Ledger coverage {evidence_fact_complete_count}/{item_count} is incomplete.",
            )
        )
    return blockers


def _evaluation_blockers(quality_inputs: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if not bool(quality_inputs.get("coverage_matrix_passed")):
        missing_areas = [str(area) for area in quality_inputs.get("coverage_missing_areas") or []]
        blockers.append(
            _blocker(
                "coverage_matrix_not_passed",
                "Missing required evidence coverage areas: " + ", ".join(missing_areas or ["unknown"]),
            )
        )
    if str(quality_inputs.get("coding_agent_evaluation_status") or "") != "passed":
        evaluation_blockers = quality_inputs.get("coding_agent_evaluation_blockers") or ["unknown"]
        blockers.append(
            _blocker(
                "coding_agent_evaluation_failed",
                "Coding-agent evaluation failed: " + "; ".join(str(item) for item in evaluation_blockers),
            )
        )
    if str(quality_inputs.get("adversarial_review_status") or "") != "passed":
        blockers.append(
            _blocker(
                "adversarial_review_failed",
                "Adversarial review found blockers: "
                + "; ".join(str(item) for item in quality_inputs.get("adversarial_review_blockers") or ["unknown"]),
            )
        )
    return blockers


def _item_metadata_blockers(quality_inputs: dict[str, Any]) -> list[dict[str, str]]:
    item_count = int(quality_inputs.get("item_count") or 0)
    metadata_complete_count = int(quality_inputs.get("item_metadata_complete_count") or 0)
    if not (item_count > 0 and metadata_complete_count < item_count):
        return []
    return [
        _blocker(
            "incomplete_retrievable_items",
            f"Retrievable item metadata coverage {metadata_complete_count}/{item_count} is incomplete.",
        )
    ]


def _quality_report(
    quality_inputs: dict[str, Any],
    *,
    archived_count: int,
    planned_count: int,
    min_archived_sources: int,
    source_audit_counts: dict[str, Any],
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "passed": not blockers,
        "archived_source_count": archived_count,
        "planned_source_count": planned_count,
        "min_archived_sources": min_archived_sources,
        "retrievable_item_count": int(quality_inputs.get("item_count") or 0),
        "item_evidence_complete_count": int(quality_inputs.get("item_evidence_complete_count") or 0),
        "item_evidence_fact_complete_count": int(quality_inputs.get("item_evidence_fact_complete_count") or 0),
        "item_metadata_complete_count": int(quality_inputs.get("item_metadata_complete_count") or 0),
        "evidence_fact_count": int(quality_inputs.get("evidence_fact_count") or 0),
        "coverage_matrix_passed": bool(quality_inputs.get("coverage_matrix_passed")),
        "coverage_missing_areas": list(quality_inputs.get("coverage_missing_areas") or []),
        "coding_agent_evaluation_status": str(quality_inputs.get("coding_agent_evaluation_status") or ""),
        "coding_agent_evaluation_blockers": list(quality_inputs.get("coding_agent_evaluation_blockers") or []),
        "adversarial_review_status": str(quality_inputs.get("adversarial_review_status") or ""),
        "adversarial_review_blockers": list(quality_inputs.get("adversarial_review_blockers") or []),
        "source_audit_counts": source_audit_counts,
        "source_audit_complete_count": int(quality_inputs.get("source_audit_complete_count") or 0),
        "quality_inputs": quality_inputs,
        "blockers": blockers,
    }


def _build_compatibility_facts(
    manifest: dict[str, Any],
    *,
    stack_key: str,
    source_versions: dict[str, str],
    target_versions: dict[str, str],
) -> dict[str, Any]:
    quality_inputs = dict(manifest.get("quality_inputs") or {})
    sources = list(manifest.get("sources") or [])
    return {
        "schema_version": 1,
        "stack_key": stack_key,
        "source_versions": source_versions,
        "target_versions": target_versions,
        "source_type_counts": quality_inputs.get("source_type_counts") or {},
        "trust_tier_counts": quality_inputs.get("trust_tier_counts") or {},
        "target_version_exactness": quality_inputs.get("target_version_exactness") or {},
        "archived_source_keys": [
            str(source.get("source_key") or "")
            for source in sources
            if source.get("checksum") and source.get("fetch_status") == "fetched"
        ],
    }
