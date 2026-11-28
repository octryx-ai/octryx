"""Why a queued Action run has not started yet, as a fixed safe code."""

from __future__ import annotations

from typing import Any

#: The skip reasons ``select_dispatch_worker`` returns when it finds no worker (``_decision("skipped", ...)``).
QUEUE_WAIT_REASONS: frozenset[str] = frozenset(
    {
        "no_available_workers",
        "required_worker_unavailable",
        "paused_due_to_rate_limit",
        "routing_policy_missing",
        "no_configured_route",
    }
)


def queue_wait_reason(run_status: Any, queue_entry: Any | None) -> str | None:
    if queue_entry is None or run_status != "queued":
        return None
    if getattr(queue_entry, "status", None) != "pending" or getattr(queue_entry, "completed_at", None) is not None:
        return None
    reason = getattr(queue_entry, "last_error", None)
    return reason if isinstance(reason, str) and reason in QUEUE_WAIT_REASONS else None


__all__ = ["QUEUE_WAIT_REASONS", "queue_wait_reason"]
