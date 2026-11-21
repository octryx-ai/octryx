from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.coding_discipline.helpers import _coerce_list
from app.services.coding_discipline.recommendation_scoring import (
    _is_routable_recommendation_candidate,
    _recommendation_confidence,
    _recommendation_reason,
)
from app.services.coding_discipline.stats import coding_discipline_stats as _coding_discipline_stats_impl


async def coding_discipline_stats(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await _coding_discipline_stats_impl(
        db,
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        limit=limit,
        recommend_models_func=recommend_coding_models,
    )


def _group_candidate_rows(payload: dict[str, Any], *, min_turns: int) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _coerce_list(payload.get("rows")):
        if not isinstance(row, dict):
            continue
        if int(row.get("turn_count") or 0) < min_turns:
            continue
        if not _is_routable_recommendation_candidate(row):
            continue
        grouped[str(row.get("discipline") or "").strip()].append(row)
    return grouped


def _candidate_score(row: dict[str, Any], max_duration: float | None) -> float:
    success_rate = float(row.get("success_rate") or 0.0)
    quality_pass_rate = float(row.get("quality_pass_rate") or success_rate)
    fallback_penalty = float(row.get("fallback_rate") or 0.0)
    verification_pass_rate = float(row.get("verification_pass_rate") or quality_pass_rate)
    verification_coverage = float(row.get("verification_coverage_rate") or 0.0)
    discipline_alignment = float(row.get("discipline_alignment_score") or 0.0)
    code_intelligence_rate = float(row.get("code_intelligence_rate") or 0.0)
    productive_turn_rate = float(row.get("productive_turn_rate") or 0.0)
    transitional_stall_rate = float(row.get("transitional_stall_rate") or 0.0)
    runtime_failure_rate = float(row.get("runtime_failure_rate") or 0.0)
    speed_score = 0.5
    if max_duration and row.get("avg_request_duration_ms") is not None and max_duration > 0:
        speed_score = max(0.0, 1.0 - (float(row["avg_request_duration_ms"]) / max_duration))
    return (
        (success_rate * 0.22)
        + (quality_pass_rate * 0.18)
        + (verification_pass_rate * 0.14)
        + (verification_coverage * 0.1)
        + (discipline_alignment * 0.1)
        + (code_intelligence_rate * 0.06)
        + (productive_turn_rate * 0.14)
        + (speed_score * 0.08)
        - (fallback_penalty * 0.08)
        - (transitional_stall_rate * 0.18)
        - (runtime_failure_rate * 0.22)
    )


def _best_candidate(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    duration_values = [
        float(row["avg_request_duration_ms"]) for row in rows if row.get("avg_request_duration_ms") is not None
    ]
    max_duration = max(duration_values) if duration_values else None
    best_row = None
    best_score = -1.0
    for row in rows:
        score = _candidate_score(row, max_duration)
        if score > best_score:
            best_score = score
            best_row = row
    return best_row, best_score


def _recommendation_payload(best_row: dict[str, Any], best_score: float) -> dict[str, Any]:
    confidence = _recommendation_confidence(best_row)
    return {
        "model_id": str(best_row.get("model_id") or ""),
        "provider_name": str(best_row.get("provider_name") or ""),
        "provider_display_name": str(best_row.get("provider_display_name") or ""),
        "driver": best_row.get("driver"),
        "runtime_kind": best_row.get("runtime_kind"),
        "score": round(best_score, 4),
        "confidence": round(confidence, 4),
        "turn_count": int(best_row.get("turn_count") or 0),
        "success_rate": best_row.get("success_rate"),
        "quality_pass_rate": best_row.get("quality_pass_rate"),
        "productive_turn_rate": best_row.get("productive_turn_rate"),
        "transitional_stall_rate": best_row.get("transitional_stall_rate"),
        "runtime_failure_rate": best_row.get("runtime_failure_rate"),
        "verification_pass_rate": best_row.get("verification_pass_rate"),
        "verification_coverage_rate": best_row.get("verification_coverage_rate"),
        "discipline_alignment_score": best_row.get("discipline_alignment_score"),
        "avg_request_duration_ms": best_row.get("avg_request_duration_ms"),
        "fallback_rate": best_row.get("fallback_rate"),
        "routing_reason": _recommendation_reason(row=best_row, score=best_score, confidence=confidence),
    }


async def recommend_coding_models(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: str | None = None,
    min_turns: int = 2,
    stats_payload: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    payload = stats_payload or await coding_discipline_stats(
        db,
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        limit=500,
    )
    grouped = _group_candidate_rows(payload, min_turns=min_turns)
    recommendations: dict[str, dict[str, Any]] = {}
    for discipline, rows in grouped.items():
        if not discipline or not rows:
            continue
        best_row, best_score = _best_candidate(rows)
        if best_row is None:
            continue
        recommendations[discipline] = _recommendation_payload(best_row, best_score)
    return recommendations
