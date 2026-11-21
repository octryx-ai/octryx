"""Contract: flow runtime failure records are typed and carry fixed facts only (X6)."""

from __future__ import annotations

import json

import httpx

from app.agent.core.runtime.runtime_errors import ProviderRuntimeError
from app.services.runtime_failure_errors import FAILURE_SUMMARIES, tool_result_failure_error
from app.services.runtime_failure_taxonomy import classify_runtime_failure

FAKE_TOKEN = ("ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123")
CREDENTIALED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
# Keyword-like wording: none of it may steer the category.
KEYWORD_BAIT = "timed out, blocked by policy, not found, validation, rate limit"
POISONED = f"{KEYWORD_BAIT}: {FAKE_TOKEN} {CREDENTIALED_URL} {INTERNAL_PATH}"


def _assert_clean(record: dict) -> None:
    serialized = json.dumps(record)
    for marker in (FAKE_TOKEN, "tok3n", CREDENTIALED_URL, INTERNAL_PATH, KEYWORD_BAIT):
        assert marker not in serialized


def test_failure_record_is_classified_by_type_and_never_keeps_the_message():
    provider = classify_runtime_failure(
        ProviderRuntimeError(POISONED, error_class="timeout", status_code=503),
        source="node_execution",
        node_id="agent",
        node_type="agent_step",
    )
    assert provider["category"] == "provider_or_runtime_unavailable"
    assert provider["retryable"] is True
    assert provider["error_class_source"] == "explicit"
    assert provider["summary"] == f"{FAILURE_SUMMARIES['provider_or_runtime_unavailable']} error_type=ProviderRuntimeError"
    assert provider["detail"] == {
        "node_id": "agent",
        "node_type": "agent_step",
        "error_type": "ProviderRuntimeError",
        "runtime_error_class": "timeout",
        "http_status": 503,
    }

    transport = classify_runtime_failure(
        httpx.ConnectTimeout(POISONED), source="node_execution", node_id="tool", node_type="tool_step"
    )
    assert (transport["category"], transport["retryable"], transport["error_class_source"]) == (
        "tool_error",
        True,
        "exception_type",
    )

    untyped = classify_runtime_failure(ValueError(POISONED), source="node_execution", node_type="agent_step")
    assert (untyped["category"], untyped["retryable"], untyped["error_class_source"]) == (
        "runtime_exception",
        False,
        "default",
    )
    assert untyped["summary"] == "Runtime execution failed. error_type=ValueError"
    for record in (provider, transport, untyped):
        assert "original_error" not in record["detail"]
        _assert_clean(record)


def test_tool_result_failure_uses_the_tool_results_own_metadata():
    denied = tool_result_failure_error({"error": POISONED, "tool_execution": {"category": "denied_by_policy"}})
    retryable = tool_result_failure_error(
        {"error": POISONED, "tool_execution": {"category": "provider_failure", "retryable": True}}
    )
    wording_only = tool_result_failure_error({"error": POISONED})

    denied_record = classify_runtime_failure(denied, source="node_execution", node_type="tool_step")
    retry_record = classify_runtime_failure(retryable, source="node_execution", node_type="tool_step")
    wording_record = classify_runtime_failure(wording_only, source="node_execution", node_type="tool_step")

    assert (denied_record["category"], denied_record["required_action"]) == ("policy_blocked", "review_policy")
    assert (retry_record["category"], retry_record["retryable"], retry_record["required_action"]) == (
        "tool_error",
        True,
        "retry_tool",
    )
    assert retry_record["detail"]["tool_category"] == "provider_failure"
    # "blocked by policy" in the error text alone is not a policy refusal.
    assert (wording_record["category"], wording_record["retryable"]) == ("tool_error", False)
    for record in (denied_record, retry_record, wording_record):
        assert record["error_class_source"] == "explicit"
        _assert_clean(record)
