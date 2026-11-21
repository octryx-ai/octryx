"""Runtime attempt metadata helpers for engine fallback flows."""

from __future__ import annotations

from typing import Any


def _build_runtime_attempt(
    runtime: dict[str, Any],
    *,
    status: str,
    retry_index: int,
    duration_ms: int | None = None,
    error: str | None = None,
    error_class: str | None = None,
    error_class_source: str | None = None,
    attempt_stage: str | None = None,
    retry_decision: str | None = None,
    retry_history: list[dict[str, Any]] | None = None,
    empty_assistant_output: bool = False,
    retry_cycle_index: int | None = None,
) -> dict[str, Any]:
    attempt = {
        "provider": runtime.get("provider_name"),
        "model": runtime.get("model"),
        "target_id": runtime.get("target_id"),
        "priority": runtime.get("priority"),
        "status": status,
        "retry_index": retry_index,
    }
    if duration_ms is not None:
        attempt["duration_ms"] = duration_ms
    if error is not None:
        attempt["error"] = error
    if error_class is not None:
        attempt["error_class"] = error_class
    if error_class_source is not None:
        attempt["error_class_source"] = error_class_source
    if attempt_stage is not None:
        attempt["attempt_stage"] = attempt_stage
    if retry_decision is not None:
        attempt["retry_decision"] = retry_decision
    if retry_history:
        attempt["retry_history"] = [dict(item) for item in retry_history]
    if empty_assistant_output:
        attempt["empty_assistant_output"] = True
    if retry_cycle_index is not None:
        attempt["retry_cycle_index"] = retry_cycle_index
    return attempt


def _record_retry_history(
    retry_history: list[dict[str, Any]],
    *,
    retry_index: int,
    error_class: str,
    retry_decision: str,
    error: str,
) -> None:
    retry_history.append(
        {
            "retry_index": retry_index,
            "error_class": error_class,
            "retry_decision": retry_decision,
            "error": error,
        }
    )
