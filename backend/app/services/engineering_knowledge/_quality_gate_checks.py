"""Gate results, policy normalisation and node-only quality gates for Engineering Knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import EngineeringKnowledgeGraphNode
from ...time_utils import utc_now

DEFAULT_GOLD_POLICY = {
    "min_evidence_count": 1,
    "min_source_types": 1,
    "min_confidence_score": 0.8,
    "allowed_verification_statuses": ["verified", "negative"],
    "allowed_classifications": ["public", "internal", "confidential"],
}


@dataclass(frozen=True)
class QualityGateResult:
    key: str
    label: str
    status: str
    severity: str
    message: str
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


def _quality_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(policy or {})
    return {
        "min_evidence_count": max(1, int(raw.get("min_evidence_count") or DEFAULT_GOLD_POLICY["min_evidence_count"])),
        "min_source_types": max(1, int(raw.get("min_source_types") or DEFAULT_GOLD_POLICY["min_source_types"])),
        "min_confidence_score": max(
            0.0,
            min(float(raw.get("min_confidence_score") or DEFAULT_GOLD_POLICY["min_confidence_score"]), 1.0),
        ),
        "allowed_verification_statuses": [
            str(value).strip().lower()
            for value in (
                raw.get("allowed_verification_statuses") or DEFAULT_GOLD_POLICY["allowed_verification_statuses"]
            )
            if str(value).strip()
        ],
        "allowed_classifications": [
            str(value).strip().lower()
            for value in (raw.get("allowed_classifications") or DEFAULT_GOLD_POLICY["allowed_classifications"])
            if str(value).strip()
        ],
    }


def _source_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _is_fresh(node: EngineeringKnowledgeGraphNode, lifecycle: dict[str, Any]) -> bool:
    if node.status in {"stale", "expired", "retracted", "rejected"}:
        return False
    if str(lifecycle.get("state") or "") in {"stale", "expired", "retracted", "rejected"}:
        return False
    return node.valid_until is None or node.valid_until > utc_now()


def _freshness_message(node: EngineeringKnowledgeGraphNode, lifecycle: dict[str, Any]) -> str:
    if lifecycle.get("reason"):
        return str(lifecycle["reason"])
    if node.valid_until and node.valid_until <= utc_now():
        return "Validity window has expired."
    return f"Fact status is {node.status}."


def _gate(
    key: str,
    label: str,
    passed: bool,
    message: str,
    evidence: dict[str, Any],
    *,
    severity: str = "blocking",
) -> QualityGateResult:
    return QualityGateResult(
        key=key,
        label=label,
        status="passed" if passed else "failed",
        severity=severity,
        message=message,
        evidence=evidence,
    )


def _quality_score(gates: list[QualityGateResult]) -> float:
    if not gates:
        return 0.0
    passed = sum(1 for gate in gates if gate.status == "passed")
    return round(passed / len(gates), 3)


def _static_gates(
    node: EngineeringKnowledgeGraphNode,
    *,
    safe_policy: dict[str, Any],
    source_refs: list[dict[str, Any]],
    lifecycle: dict[str, Any],
) -> list[QualityGateResult]:
    """The gates that read only the node itself, in report order."""
    distinct_source_types = sorted({str(ref.get("source_type") or "unknown") for ref in source_refs})
    return [
        _gate(
            "evidence_coverage",
            "Evidence coverage",
            len(source_refs) >= safe_policy["min_evidence_count"],
            f"{len(source_refs)}/{safe_policy['min_evidence_count']} source references attached.",
            {"source_ref_count": len(source_refs), "required": safe_policy["min_evidence_count"]},
        ),
        _gate(
            "source_diversity",
            "Source diversity",
            len(distinct_source_types) >= safe_policy["min_source_types"],
            f"{len(distinct_source_types)}/{safe_policy['min_source_types']} source types represented.",
            {"source_types": distinct_source_types, "required": safe_policy["min_source_types"]},
            severity="warning" if safe_policy["min_source_types"] <= 1 else "blocking",
        ),
        _gate(
            "freshness",
            "Freshness",
            _is_fresh(node, lifecycle),
            _freshness_message(node, lifecycle),
            {"status": node.status, "valid_until": node.valid_until.isoformat() if node.valid_until else None},
        ),
        _gate(
            "trust_level",
            "Trust level",
            node.trust_level in {"gold", "official", "verified"},
            f"Trust level is {node.trust_level}.",
            {"trust_level": node.trust_level},
        ),
        _gate(
            "classification",
            "Classification",
            node.classification in safe_policy["allowed_classifications"],
            f"Classification is {node.classification}.",
            {"classification": node.classification, "allowed": safe_policy["allowed_classifications"]},
        ),
    ]
