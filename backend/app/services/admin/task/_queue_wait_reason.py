"""Why a queued Action run has not started yet, as a fixed safe code.

The dispatcher records why it skipped a pending queue entry in ``TaskQueueEntry.last_error``
(``scheduler/dispatch/loop.py``), using the reason codes of
``services/worker_pool/dispatch.select_dispatch_worker``. The same column also holds free text
(an expiry message, a queue-backend note, a failed run's error), so it is never returned as is:
only a whitelisted code is, and only while the run is still waiting. A completed, cancelled,
assigned or otherwise no-longer-waiting run reports no reason, so an obsolete blocker is never
shown after the run moved on.
"""

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
    """The whitelisted waiting reason of a still-queued run, else ``None``."""
    if queue_entry is None or run_status != "queued":
        return None
    if getattr(queue_entry, "status", None) != "pending" or getattr(queue_entry, "completed_at", None) is not None:
        return None
    reason = getattr(queue_entry, "last_error", None)
    return reason if isinstance(reason, str) and reason in QUEUE_WAIT_REASONS else None


__all__ = ["QUEUE_WAIT_REASONS", "queue_wait_reason"]
