"""Per-trace accumulation of the coding-discipline stats into discipline/provider/model buckets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.coding_discipline.helpers import (
    _coding_discipline_for_trace,
    _coerce_dict,
    _coerce_float,
    _coerce_list,
    _discipline_alignment_score,
    _extract_successful_attempt,
    _productivity_metrics_for_trace,
    _quality_signal_for_trace,
    _verification_metrics_for_trace,
)

from ...models import ControlPlaneRuntimeTarget, LLMProvider, TurnTrace
from ...time_utils import ensure_utc

# (metrics key, counter) pairs counted once per turn on both the bucket and the discipline summary,
# in the order the counters were always bumped.
_PRODUCTIVITY_COUNTERS = (
    ("productive", "productive_turn_count"),
    ("transitional_stall", "transitional_stall_turn_count"),
)
_VERIFICATION_COUNTERS = (
    ("verification_seen", "verification_turn_count"),
    ("verification_passed", "verification_pass_count"),
    ("tests_seen", "tests_turn_count"),
    ("tests_passed", "tests_pass_count"),
    ("formatting_seen", "formatting_turn_count"),
    ("formatting_passed", "formatting_pass_count"),
    ("review_seen", "review_turn_count"),
    ("review_passed", "review_pass_count"),
)
_ZERO_COUNTERS = (
    "turn_count",
    "success_count",
    "quality_turn_count",
    "quality_pass_count",
    "fallback_turn_count",
    "productive_turn_count",
    "transitional_stall_turn_count",
    "runtime_failure_attempt_count",
    "verification_turn_count",
    "verification_pass_count",
    "code_intelligence_turn_count",
    "code_intelligence_calls",
    "quality_calls",
    "tests_turn_count",
    "tests_pass_count",
    "formatting_turn_count",
    "formatting_pass_count",
    "review_turn_count",
    "review_pass_count",
)


@dataclass
class BucketBook:
    """The buckets of one stats call and the provider rows they are labelled with."""

    runtime_targets: dict[str, ControlPlaneRuntimeTarget]
    providers_by_name: dict[str, LLMProvider]
    providers_by_id: dict[str, LLMProvider]
    discipline_summary: dict[str, dict[str, Any]]
    buckets: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)

    def bucket_for_candidate(
        self, *, discipline: str, provider_name: str, model_id: str, target_id: str = ""
    ) -> dict[str, Any]:
        runtime_target = self.runtime_targets.get(target_id) if target_id else None
        provider_row = (
            self.providers_by_id.get(runtime_target.provider_id)
            if runtime_target and runtime_target.provider_id
            else self.providers_by_name.get(provider_name)
        )
        key = (discipline, provider_name, model_id)
        return self.buckets.setdefault(key, _new_bucket(discipline, provider_name, model_id, provider_row))


def _new_bucket(discipline: str, provider_name: str, model_id: str, provider_row: Any) -> dict[str, Any]:
    return {
        "discipline": discipline,
        "provider_name": provider_name,
        "provider_display_name": provider_row.display_name
        if provider_row and provider_row.display_name
        else provider_name,
        "provider_family": provider_row.provider_family if provider_row else None,
        "driver": provider_row.driver if provider_row else None,
        "runtime_kind": provider_row.runtime_kind if provider_row else None,
        "profile_name": provider_row.profile_name if provider_row else None,
        "model_id": model_id,
        **dict.fromkeys(_ZERO_COUNTERS, 0),
        "discipline_alignment_scores": [],
        "request_durations": [],
        "last_seen_at": None,
    }


def _bump(bucket: dict[str, Any], summary: dict[str, Any], counter: str) -> None:
    bucket[counter] += 1
    summary[counter] += 1


def _count_signals(trace: TurnTrace, discipline: str, bucket: dict[str, Any], summary: dict[str, Any]) -> None:
    quality_seen, quality_passed = _quality_signal_for_trace(trace)
    if quality_seen:
        _bump(bucket, summary, "quality_turn_count")
    if quality_passed:
        _bump(bucket, summary, "quality_pass_count")
    verification_metrics = _verification_metrics_for_trace(trace)
    productivity_metrics = _productivity_metrics_for_trace(trace)
    bucket["code_intelligence_calls"] += int(verification_metrics["code_intelligence_calls"])
    bucket["quality_calls"] += int(verification_metrics["quality_calls"])
    for metric, counter in _PRODUCTIVITY_COUNTERS:
        if productivity_metrics[metric]:
            _bump(bucket, summary, counter)
    if int(verification_metrics["code_intelligence_calls"]) > 0:
        _bump(bucket, summary, "code_intelligence_turn_count")
    for metric, counter in _VERIFICATION_COUNTERS:
        if verification_metrics[metric]:
            _bump(bucket, summary, counter)
    bucket["discipline_alignment_scores"].append(
        _discipline_alignment_score(discipline=discipline, metrics=verification_metrics)
    )


def _record_timing(trace: TurnTrace, usage: dict[str, Any], success_attempt: Any, bucket: dict[str, Any]) -> None:
    request_duration_ms = _coerce_float(usage.get("request_duration_ms"))
    if request_duration_ms is None:
        request_duration_ms = _coerce_float((success_attempt or {}).get("duration_ms"))
    if request_duration_ms is not None:
        bucket["request_durations"].append(request_duration_ms)
    created_at = ensure_utc(trace.created_at)
    if created_at and (bucket["last_seen_at"] is None or created_at > bucket["last_seen_at"]):
        bucket["last_seen_at"] = created_at


def _count_failed_attempts(book: BucketBook, discipline: str, raw_output: dict[str, Any]) -> None:
    for attempt in [item for item in _coerce_list(raw_output.get("runtime_attempts")) if isinstance(item, dict)]:
        attempt_status = str(attempt.get("status") or "").strip().lower()
        attempt_provider = str(attempt.get("provider") or "").strip()
        attempt_model = str(attempt.get("model") or "").strip()
        if not attempt_provider or not attempt_model or attempt_status == "success":
            continue
        attempt_target_id = str(attempt.get("target_id") or "").strip()
        attempt_bucket = book.bucket_for_candidate(
            discipline=discipline,
            provider_name=attempt_provider,
            model_id=attempt_model,
            target_id=attempt_target_id,
        )
        attempt_bucket["runtime_failure_attempt_count"] += 1
        book.discipline_summary[discipline]["runtime_failure_attempt_count"] += 1


def accumulate_trace(book: BucketBook, trace: TurnTrace) -> None:
    """Count one turn into its bucket and its discipline's summary; a turn without provider and model is skipped."""
    discipline = _coding_discipline_for_trace(trace)
    raw_output = _coerce_dict(trace.raw_output)
    usage = _coerce_dict(trace.usage_json)
    success_attempt = _extract_successful_attempt(
        raw_output,
        provider_name=str(trace.provider or "").strip(),
        model_id=str(trace.model or "").strip(),
    )
    provider_name = str((success_attempt or {}).get("provider") or trace.provider or "").strip()
    model_id = str((success_attempt or {}).get("model") or trace.model or "").strip()
    if not provider_name and not model_id:
        return
    target_id = str((success_attempt or {}).get("target_id") or "").strip()
    bucket = book.bucket_for_candidate(
        discipline=discipline,
        provider_name=provider_name,
        model_id=model_id,
        target_id=target_id,
    )
    summary = book.discipline_summary[discipline]
    _bump(bucket, summary, "turn_count")
    attempts = [item for item in _coerce_list(raw_output.get("runtime_attempts")) if isinstance(item, dict)]
    if len(attempts) > 1:
        _bump(bucket, summary, "fallback_turn_count")
    runtime_error = str(raw_output.get("error") or "").strip()
    success = bool(success_attempt) or not runtime_error
    if success:
        _bump(bucket, summary, "success_count")
    _count_signals(trace, discipline, bucket, summary)
    _record_timing(trace, usage, success_attempt, bucket)
    _count_failed_attempts(book, discipline, raw_output)
