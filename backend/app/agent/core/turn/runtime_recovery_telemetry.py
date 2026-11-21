"""Structured telemetry helpers for runtime retry and fallback recovery."""

from __future__ import annotations

from typing import Any


def summarize_runtime_recovery(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not attempts:
        return None

    error_attempts = [attempt for attempt in attempts if attempt.get("status") == "error"]
    skipped_attempts = [attempt for attempt in attempts if attempt.get("status") == "skipped"]
    retry_attempts = [attempt for attempt in attempts if attempt.get("retry_decision") == "same_runtime_retry"]
    fallback_attempts = [attempt for attempt in attempts if attempt.get("retry_decision") == "fallback_next_runtime"]
    if not error_attempts and not skipped_attempts and not retry_attempts and not fallback_attempts:
        return None

    summary: dict[str, Any] = {
        "attempt_count": len(attempts),
        "error_count": len(error_attempts),
        "final_status": str(attempts[-1].get("status") or "unknown"),
    }
    if skipped_attempts:
        summary["skipped_count"] = len(skipped_attempts)
    if retry_attempts:
        summary["same_runtime_retry_count"] = len(retry_attempts)
    if fallback_attempts:
        summary["fallback_count"] = len(fallback_attempts)

    error_class_counts: dict[str, int] = {}
    for attempt in error_attempts:
        error_class = str(attempt.get("error_class") or "").strip()
        if error_class:
            error_class_counts[error_class] = error_class_counts.get(error_class, 0) + 1
    if error_class_counts:
        summary["error_classes"] = error_class_counts

    total_duration_ms = sum(
        int(duration_ms)
        for duration_ms in (attempt.get("duration_ms") for attempt in attempts)
        if isinstance(duration_ms, (int, float))
    )
    if total_duration_ms > 0:
        summary["total_duration_ms"] = total_duration_ms

    final_attempt = attempts[-1]
    final_target = str(final_attempt.get("target_id") or "").strip()
    if final_target:
        summary["final_target_id"] = final_target
    final_provider = str(final_attempt.get("provider") or "").strip()
    if final_provider:
        summary["final_provider"] = final_provider
    final_model = str(final_attempt.get("model") or "").strip()
    if final_model:
        summary["final_model"] = final_model
    if final_attempt.get("status") == "success" and error_attempts:
        summary["recovered"] = True
    return summary


def attach_runtime_recovery_telemetry(
    attempts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    summary = summarize_runtime_recovery(attempts)
    if not summary:
        return attempts, None
    annotated_attempts = [dict(attempt) for attempt in attempts]
    annotated_attempts[-1]["runtime_recovery"] = dict(summary)
    return annotated_attempts, summary


__all__ = ["attach_runtime_recovery_telemetry", "summarize_runtime_recovery"]
