from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.coding_discipline.helpers import (
    _coerce_dict,
    _coerce_list,
    _extract_successful_attempt,
    _mean,
    _percentile,
)

from ...models import ControlPlaneRuntimeTarget, LLMProvider, TurnTrace
from ...models import Session as AgentSession


def init_discipline_summary() -> dict[str, dict[str, Any]]:
    return defaultdict(
        lambda: {
            "turn_count": 0,
            "success_count": 0,
            "quality_turn_count": 0,
            "quality_pass_count": 0,
            "fallback_turn_count": 0,
            "productive_turn_count": 0,
            "transitional_stall_turn_count": 0,
            "runtime_failure_attempt_count": 0,
            "verification_turn_count": 0,
            "verification_pass_count": 0,
            "code_intelligence_turn_count": 0,
            "tests_turn_count": 0,
            "tests_pass_count": 0,
            "formatting_turn_count": 0,
            "formatting_pass_count": 0,
            "review_turn_count": 0,
            "review_pass_count": 0,
        }
    )


def collect_target_and_provider_names(rows: list[tuple[TurnTrace, AgentSession]]) -> tuple[set[str], set[str]]:
    target_ids: set[str] = set()
    provider_names: set[str] = set()
    for trace, _session in rows:
        raw_output = _coerce_dict(trace.raw_output)
        success_attempt = _extract_successful_attempt(
            raw_output,
            provider_name=str(trace.provider or "").strip(),
            model_id=str(trace.model or "").strip(),
        )
        target_id = str((success_attempt or {}).get("target_id") or "").strip()
        if target_id:
            target_ids.add(target_id)
        for attempt in _coerce_list(raw_output.get("runtime_attempts")):
            if not isinstance(attempt, dict):
                continue
            attempt_target_id = str(attempt.get("target_id") or "").strip()
            if attempt_target_id:
                target_ids.add(attempt_target_id)
        provider_name = str((success_attempt or {}).get("provider") or trace.provider or "").strip()
        if provider_name:
            provider_names.add(provider_name)
        for attempt in _coerce_list(raw_output.get("runtime_attempts")):
            if not isinstance(attempt, dict):
                continue
            attempt_provider_name = str(attempt.get("provider") or "").strip()
            if attempt_provider_name:
                provider_names.add(attempt_provider_name)
    return target_ids, provider_names


async def load_provider_maps(
    db: AsyncSession,
    *,
    target_ids: set[str],
    provider_names: set[str],
) -> tuple[dict[str, ControlPlaneRuntimeTarget], dict[str, LLMProvider], dict[str, LLMProvider]]:
    runtime_targets = (
        {
            row.id: row
            for row in (
                await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.id.in_(target_ids)))
            )
            .scalars()
            .all()
        }
        if target_ids
        else {}
    )

    providers_by_name: dict[str, LLMProvider] = {}
    if provider_names:
        provider_rows = (
            (await db.execute(select(LLMProvider).where(LLMProvider.name.in_(provider_names)))).scalars().all()
        )
        for provider in provider_rows:
            current = providers_by_name.get(provider.name)
            if current is None or (not current.is_active and provider.is_active):
                providers_by_name[provider.name] = provider

    providers_by_id = (
        {
            row.id: row
            for row in (
                await db.execute(
                    select(LLMProvider).where(
                        LLMProvider.id.in_({item.provider_id for item in runtime_targets.values() if item.provider_id})
                    )
                )
            )
            .scalars()
            .all()
        }
        if runtime_targets
        else {}
    )

    return runtime_targets, providers_by_name, providers_by_id


def _bucket_identity(bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "discipline": bucket["discipline"],
        "provider_name": bucket["provider_name"],
        "provider_display_name": bucket["provider_display_name"],
        "provider_family": bucket["provider_family"],
        "driver": bucket["driver"],
        "runtime_kind": bucket["runtime_kind"],
        "profile_name": bucket["profile_name"],
        "model_id": bucket["model_id"],
    }


def _bucket_turn_rates(bucket: dict[str, Any]) -> dict[str, Any]:
    turn_count = int(bucket["turn_count"])
    observed_attempt_count = turn_count + int(bucket["runtime_failure_attempt_count"])
    rate_denominator = max(1, observed_attempt_count)
    success_rate = float(bucket["success_count"]) / max(1, turn_count)
    quality_turn_count = int(bucket["quality_turn_count"])
    quality_pass_rate = float(bucket["quality_pass_count"]) / quality_turn_count if quality_turn_count else None
    fallback_rate = float(bucket["fallback_turn_count"]) / max(1, turn_count)
    verification_turn_count = int(bucket["verification_turn_count"])
    verification_pass_rate = (
        float(bucket["verification_pass_count"]) / verification_turn_count if verification_turn_count else None
    )
    return {
        "turn_count": int(bucket["turn_count"]),
        "success_count": int(bucket["success_count"]),
        "success_rate": success_rate,
        "quality_turn_count": quality_turn_count,
        "quality_pass_count": int(bucket["quality_pass_count"]),
        "quality_pass_rate": quality_pass_rate,
        "productive_turn_count": int(bucket["productive_turn_count"]),
        "productive_turn_rate": float(bucket["productive_turn_count"]) / max(1, turn_count),
        "transitional_stall_turn_count": int(bucket["transitional_stall_turn_count"]),
        "transitional_stall_rate": float(bucket["transitional_stall_turn_count"]) / max(1, turn_count),
        "runtime_failure_attempt_count": int(bucket["runtime_failure_attempt_count"]),
        "runtime_failure_rate": float(bucket["runtime_failure_attempt_count"]) / rate_denominator,
        "verification_turn_count": verification_turn_count,
        "verification_pass_count": int(bucket["verification_pass_count"]),
        "verification_pass_rate": verification_pass_rate,
        "verification_coverage_rate": float(verification_turn_count) / max(1, turn_count),
        "fallback_turn_count": int(bucket["fallback_turn_count"]),
        "fallback_rate": fallback_rate,
        "code_intelligence_turn_count": int(bucket["code_intelligence_turn_count"]),
        "code_intelligence_rate": float(bucket["code_intelligence_turn_count"]) / max(1, turn_count),
        "code_intelligence_calls": int(bucket["code_intelligence_calls"]),
        "quality_calls": int(bucket["quality_calls"]),
    }


def _bucket_check_rates(bucket: dict[str, Any]) -> dict[str, Any]:
    tests_turn_count = int(bucket["tests_turn_count"])
    formatting_turn_count = int(bucket["formatting_turn_count"])
    review_turn_count = int(bucket["review_turn_count"])
    return {
        "tests_turn_count": tests_turn_count,
        "tests_pass_count": int(bucket["tests_pass_count"]),
        "tests_pass_rate": (float(bucket["tests_pass_count"]) / tests_turn_count if tests_turn_count else None),
        "formatting_turn_count": formatting_turn_count,
        "formatting_pass_count": int(bucket["formatting_pass_count"]),
        "formatting_pass_rate": (
            float(bucket["formatting_pass_count"]) / formatting_turn_count if formatting_turn_count else None
        ),
        "review_turn_count": review_turn_count,
        "review_pass_count": int(bucket["review_pass_count"]),
        "review_pass_rate": (
            float(bucket["review_pass_count"]) / review_turn_count if review_turn_count else None
        ),
        "discipline_alignment_score": _mean(bucket["discipline_alignment_scores"]),
        "avg_request_duration_ms": _mean(bucket["request_durations"]),
        "p95_request_duration_ms": _percentile(bucket["request_durations"], 0.95),
        "last_seen_at": bucket["last_seen_at"].isoformat() if bucket["last_seen_at"] else None,
    }


def build_rows_out(buckets: dict[tuple[str, str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        rows_out.append({**_bucket_identity(bucket), **_bucket_turn_rates(bucket), **_bucket_check_rates(bucket)})
    rows_out.sort(
        key=lambda item: (
            item["discipline"],
            -(item["success_rate"] or 0.0),
            item["avg_request_duration_ms"] is None,
            float(item["avg_request_duration_ms"] or 0),
        )
    )
    return rows_out


def build_summary(discipline_summary: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        discipline: {
            **values,
            "success_rate": (float(values["success_count"]) / values["turn_count"]) if values["turn_count"] else None,
            "quality_pass_rate": (
                float(values["quality_pass_count"]) / values["quality_turn_count"]
                if values["quality_turn_count"]
                else None
            ),
            "productive_turn_rate": (
                float(values["productive_turn_count"]) / values["turn_count"] if values["turn_count"] else None
            ),
            "transitional_stall_rate": (
                float(values["transitional_stall_turn_count"]) / values["turn_count"] if values["turn_count"] else None
            ),
            "runtime_failure_rate": (
                float(values["runtime_failure_attempt_count"])
                / max(1, values["turn_count"] + values["runtime_failure_attempt_count"])
            ),
            "verification_pass_rate": (
                float(values["verification_pass_count"]) / values["verification_turn_count"]
                if values["verification_turn_count"]
                else None
            ),
            "verification_coverage_rate": (
                float(values["verification_turn_count"]) / values["turn_count"] if values["turn_count"] else None
            ),
            "fallback_rate": (
                float(values["fallback_turn_count"]) / values["turn_count"] if values["turn_count"] else None
            ),
            "code_intelligence_rate": (
                float(values["code_intelligence_turn_count"]) / values["turn_count"] if values["turn_count"] else None
            ),
            "tests_pass_rate": (
                float(values["tests_pass_count"]) / values["tests_turn_count"] if values["tests_turn_count"] else None
            ),
            "formatting_pass_rate": (
                float(values["formatting_pass_count"]) / values["formatting_turn_count"]
                if values["formatting_turn_count"]
                else None
            ),
            "review_pass_rate": (
                float(values["review_pass_count"]) / values["review_turn_count"]
                if values["review_turn_count"]
                else None
            ),
        }
        for discipline, values in discipline_summary.items()
    }
