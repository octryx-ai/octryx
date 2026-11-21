"""What one intake run really did with the source's items, beyond imported/updated/unchanged.

The per-run limit and paging leave items for the next run; they are *pending*, not filtered out. The
automation label never filters the import: it only marks which imported items the agent may start, so it
is reported as its own count.
"""

from __future__ import annotations

from typing import Any

from ..automation_eligibility import automation_policy_for_sync_config
from ..jira_values import object_value


def _has(labels: list[str], candidates: list[str]) -> bool:
    wanted = {candidate.strip().casefold() for candidate in candidates}
    return any(label.strip().casefold() in wanted for label in labels)


def run_counts(*, normalized: list[dict[str, Any]], source: dict[str, Any], sync_options: Any) -> dict[str, Any]:
    """`pending_next_run` (None when the source does not report its total), `more_pending`, `automation`."""
    metadata = object_value(source.get("metadata"))
    returned = metadata.get("returned")
    total = source.get("source_count")
    complete = bool(source.get("source_complete"))
    pending = None
    if not complete and isinstance(returned, int) and isinstance(total, int) and total > returned:
        pending = total - returned
    policy = automation_policy_for_sync_config(object_value(sync_options))
    matching = sum(
        1
        for item in normalized
        if _has(list(item.get("labels_json") or []), policy["trigger_labels"])
        and not _has(list(item.get("labels_json") or []), policy["exclude_labels"])
    )
    return {
        "pending_next_run": pending,
        "more_pending": not complete,
        "automation": {
            "labels": policy["trigger_labels"],
            "matching": matching,
            "mode": policy.get("mode") or "needs_review",
        },
    }
