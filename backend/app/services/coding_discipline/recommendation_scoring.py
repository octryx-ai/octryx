"""How a discipline/model row is scored as a routing recommendation: confidence, reason text, routability."""

from __future__ import annotations

from typing import Any

DISCIPLINE_RECOMMENDATION_MAX_TURNS = 12
NON_ROUTABLE_PROVIDERS = {"workflow", "system", "orchestrator"}


def _recommendation_confidence(row: dict[str, Any]) -> float:
    turn_count = max(0, int(row.get("turn_count") or 0))
    sample_score = min(1.0, turn_count / float(DISCIPLINE_RECOMMENDATION_MAX_TURNS))
    verification_coverage = float(row.get("verification_coverage_rate") or 0.0)
    quality_pass_rate = float(row.get("quality_pass_rate") or 0.0)
    success_rate = float(row.get("success_rate") or 0.0)
    code_intelligence_rate = float(row.get("code_intelligence_rate") or 0.0)
    discipline_alignment = float(row.get("discipline_alignment_score") or 0.0)
    productive_turn_rate = float(row.get("productive_turn_rate") or 0.0)
    runtime_failure_rate = float(row.get("runtime_failure_rate") or 0.0)
    confidence = (
        (sample_score * 0.34)
        + (verification_coverage * 0.15)
        + (quality_pass_rate * 0.1)
        + (success_rate * 0.2)
        + (code_intelligence_rate * 0.1)
        + (discipline_alignment * 0.05)
        + (productive_turn_rate * 0.1)
        - (runtime_failure_rate * 0.12)
    )
    return max(0.0, min(confidence, 1.0))


def _recommendation_reason(*, row: dict[str, Any], score: float, confidence: float) -> str:
    parts: list[str] = [
        f"score {round(score * 100)}%",
        f"confidence {round(confidence * 100)}%",
        f"{int(row.get('turn_count') or 0)} runs",
    ]
    if row.get("quality_pass_rate") is not None:
        parts.append(f"quality {round(float(row['quality_pass_rate']) * 100)}%")
    if row.get("verification_coverage_rate") is not None:
        parts.append(f"verification {round(float(row['verification_coverage_rate']) * 100)}%")
    if row.get("productive_turn_rate") is not None:
        parts.append(f"productive {round(float(row['productive_turn_rate']) * 100)}%")
    if row.get("runtime_failure_rate") is not None and float(row.get("runtime_failure_rate") or 0.0) > 0:
        parts.append(f"runtime failures {round(float(row['runtime_failure_rate']) * 100)}%")
    if row.get("avg_request_duration_ms") is not None:
        parts.append(f"avg {round(float(row['avg_request_duration_ms']))} ms")
    return " · ".join(parts)


def _is_routable_recommendation_candidate(row: dict[str, Any]) -> bool:
    provider_name = str(row.get("provider_name") or "").strip().lower()
    model_id = str(row.get("model_id") or "").strip().lower()
    if provider_name in NON_ROUTABLE_PROVIDERS:
        return False
    if model_id.startswith("deterministic-"):
        return False
    discipline = str(row.get("discipline") or "").strip().lower()
    productive_turn_rate = float(row.get("productive_turn_rate") or 0.0)
    transitional_stall_rate = float(row.get("transitional_stall_rate") or 0.0)
    runtime_failure_rate = float(row.get("runtime_failure_rate") or 0.0)
    if runtime_failure_rate >= 0.4:
        return False
    if transitional_stall_rate >= 0.6:
        return False
    if discipline == "planning" and productive_turn_rate < 0.2:
        return False
    if discipline in {"edit", "test-fix", "review", "repo-intelligence"} and productive_turn_rate < 0.25:
        return False
    return True
