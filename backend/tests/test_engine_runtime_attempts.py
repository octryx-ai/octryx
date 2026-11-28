"""Unit tests for runtime attempt metadata helpers."""

from __future__ import annotations

from app.agent.runtime.attempts import _build_runtime_attempt, _record_retry_history


def test_build_runtime_attempt_preserves_runtime_fields_and_metadata_copy():
    retry_history = [
        {
            "retry_index": 1,
            "error_class": "context_pressure",
            "retry_decision": "same_runtime_retry",
            "error": "context window exceeded",
        }
    ]

    attempt = _build_runtime_attempt(
        {
            "provider_name": "copilot",
            "model": "claude-haiku-4.5",
            "target_id": "ctx",
            "priority": 7,
        },
        status="success",
        retry_index=2,
        duration_ms=123,
        retry_history=retry_history,
        empty_assistant_output=True,
        retry_cycle_index=4,
    )

    retry_history[0]["error"] = "changed"

    assert attempt == {
        "provider": "copilot",
        "model": "claude-haiku-4.5",
        "target_id": "ctx",
        "priority": 7,
        "status": "success",
        "retry_index": 2,
        "duration_ms": 123,
        "retry_history": [
            {
                "retry_index": 1,
                "error_class": "context_pressure",
                "retry_decision": "same_runtime_retry",
                "error": "context window exceeded",
            }
        ],
        "empty_assistant_output": True,
        "retry_cycle_index": 4,
    }


def test_record_retry_history_appends_retry_metadata():
    retry_history: list[dict[str, object]] = []

    _record_retry_history(
        retry_history,
        retry_index=3,
        error_class="timeout",
        retry_decision="same_runtime_retry",
        error="request timed out after 5s",
    )

    assert retry_history == [
        {
            "retry_index": 3,
            "error_class": "timeout",
            "retry_decision": "same_runtime_retry",
            "error": "request timed out after 5s",
        }
    ]
