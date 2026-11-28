"""Model Policy alias failover of a governed agent run switches only on typed transient facts."""

from __future__ import annotations

import pytest

from app.services.governed_agent_run.model_failover import transient_failure


@pytest.mark.parametrize(
    "attempts",
    [
        [{"status": "skipped", "error": "runtime does not support requested tool calls"}],
        [{"status": "admission_denied", "error_class": "alias_denied", "error_class_source": "explicit"}],
        [{"status": "error", "error_class": "transient", "error_class_source": "message_pattern"}],
        [
            {"status": "error", "error_class": "transient", "error_class_source": "explicit"},
            {"status": "error", "error_class": "permanent", "error_class_source": "explicit"},
        ],
        [{"status": "fallback_denied", "error_class": "fallback_denied_by_policy"}],
        None,
    ],
    ids=["capability", "admission", "message-pattern", "mixed", "bookkeeping-only", "no-facts"],
)
def test_only_typed_transient_chains_may_switch(attempts) -> None:
    assert transient_failure(attempts) is None


def test_a_typed_transient_chain_may_switch() -> None:
    attempts = [{"status": "error", "error_class": "transient", "error_class_source": "explicit"}]
    assert transient_failure(attempts) is not None
