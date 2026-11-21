"""Deterministic coding-agent evaluation for Engineering Knowledge Packs."""

from __future__ import annotations

from typing import Any

from ...models import EngineeringKnowledgePackItem

_ACTION_TERMS = {
    "avoid",
    "check",
    "compile",
    "configure",
    "cover",
    "covers",
    "describe",
    "describes",
    "document",
    "documents",
    "include",
    "includes",
    "migrate",
    "prefer",
    "require",
    "requires",
    "remove",
    "replace",
    "review",
    "run",
    "test",
    "update",
    "use",
    "validate",
    "verify",
}


def evaluate_pack_for_coding_agent(
    *,
    items: list[EngineeringKnowledgePackItem],
    evidence_ledger: list[dict[str, Any]],
    coverage_matrix: dict[str, Any],
) -> dict[str, Any]:
    tasks = [
        {
            "task_key": "migration_workflow",
            "prompt": "Migrate a codebase from the source version to the target version.",
            "required_areas": ["migration", "removals_deprecations", "build_tooling"],
        },
        {
            "task_key": "feature_usage_policy",
            "prompt": "Decide whether a new target-version feature should be used in production code.",
            "required_areas": ["features", "security_native"],
        },
        {
            "task_key": "runtime_validation",
            "prompt": "Identify runtime, performance, native, or security risks before deployment.",
            "required_areas": ["runtime_performance", "security_native"],
        },
    ]
    covered_areas = {
        area
        for fact in evidence_ledger
        if fact.get("usable_for_pack") is True
        for area in list(fact.get("coverage_areas") or [])
    }
    task_results = []
    blockers: list[str] = []
    for task in tasks:
        missing = [area for area in task["required_areas"] if area not in covered_areas]
        task_results.append(
            {
                **task,
                "status": "passed" if not missing else "failed",
                "missing_areas": missing,
            }
        )
        if missing:
            blockers.append(f"{task['task_key']} missing areas: {', '.join(missing)}")

    item_findings = _item_actionability_findings(items)
    blockers.extend(item_findings)
    if not bool(coverage_matrix.get("passed")):
        blockers.append("coverage_matrix_not_passed")
    return {
        "schema_version": 1,
        "status": "passed" if not blockers else "failed",
        "task_results": task_results,
        "item_findings": item_findings,
        "blockers": blockers,
    }


def run_adversarial_pack_review(
    *,
    items: list[EngineeringKnowledgePackItem],
    evidence_ledger: list[dict[str, Any]],
    coverage_matrix: dict[str, Any],
) -> dict[str, Any]:
    evidence_fact_ids = {str(fact.get("fact_id") or "") for fact in evidence_ledger if fact.get("fact_id")}
    blockers: list[str] = []
    warnings: list[str] = []
    for item in items:
        metadata = dict(item.item_metadata or {})
        item_fact_ids = {str(fact_id) for fact_id in metadata.get("evidence_fact_ids") or []}
        if not item_fact_ids:
            blockers.append(f"{item.item_key}: missing Evidence Ledger fact references")
        elif not item_fact_ids.intersection(evidence_fact_ids):
            blockers.append(f"{item.item_key}: Evidence Ledger fact references do not resolve")
        if not item.triggers:
            blockers.append(f"{item.item_key}: missing retrieval triggers")
        if not item.version_scope:
            blockers.append(f"{item.item_key}: missing version_scope")
        if _looks_generic(item):
            warnings.append(f"{item.item_key}: wording may be too generic")
    for missing_area in list(coverage_matrix.get("missing_areas") or []):
        blockers.append(f"coverage missing: {missing_area}")
    return {
        "schema_version": 1,
        "status": "passed" if not blockers else "failed",
        "blockers": blockers,
        "warnings": warnings,
    }


def _item_actionability_findings(items: list[EngineeringKnowledgePackItem]) -> list[str]:
    findings: list[str] = []
    for item in items:
        content = str(item.content or "").lower()
        if not set(content.replace("-", " ").split()).intersection(_ACTION_TERMS):
            findings.append(f"{item.item_key}: no actionable coding-agent wording detected")
        if not item.triggers:
            findings.append(f"{item.item_key}: no retrieval triggers")
        if not item.version_scope:
            findings.append(f"{item.item_key}: no version_scope")
    return findings


def _looks_generic(item: EngineeringKnowledgePackItem) -> bool:
    content = " ".join(str(item.content or "").lower().split())
    if len(content) < 120:
        return True
    generic_phrases = {
        "this item captures official documentation evidence",
        "source evidence is from",
        "should be used by coding agents",
    }
    return any(phrase in content for phrase in generic_phrases)
