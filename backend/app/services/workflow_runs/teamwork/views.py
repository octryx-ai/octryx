"""What the run view shows of the coordinator's split: one box per item with its role, model, status and iteration,
the ``depends_on`` arrows, and merge or conflict marks."""

from __future__ import annotations

from typing import Any

from . import work_of
from .item_order import plan_order

ITEM_VIEW_FIELDS = ("id", "title", "role", "model", "status", "iteration", "depends_on", "paths", "proofs",
                    "session_id", "branch", "runtime_target_id", "agent_hash", "result", "reason", "conflicts",
                    "merged_sha", "started_at", "finished_at", "merged_at")


def work_view(run: Any) -> dict[str, Any] | None:
    work = work_of(run)
    items = dict(work.get("items") or {})
    if not items:
        return None
    return {"node_id": work.get("node_id"), "plan_node": work.get("plan_node"),
            "plan_version": work.get("plan_version"), "executor": work.get("executor"), "route": work.get("route"),
            "contract": work.get("contract") or "", "coordinator_hash": work.get("coordinator_hash"),
            "items": [{field: items[key].get(field) for field in ITEM_VIEW_FIELDS} for key in plan_order(items)]}


__all__ = ["work_view"]
