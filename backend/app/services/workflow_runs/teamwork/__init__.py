"""Teamwork: the coordinator splits a story's work at run time; ``parallel_work`` runs the split."""

from __future__ import annotations

from typing import Any, Protocol

from .work_types import ExecutorName, FixSource, ItemResult, ItemStatus, ResultValue, Route, SplitItem, WorkSplit

WORK_KEY = "work"
ITEM_METADATA_KEY = "workflow_run_item"
ROLE_ITEM = "item"
OUTPUT_KIND = "work_plan"
OUTPUT_TOOL = "submit_work_plan"

ROUTE_DONE, ROUTE_REPLAN = "done", "replan"
ROUTES = frozenset({ROUTE_DONE, ROUTE_REPLAN})

PENDING, RUNNING, DONE, MERGED = "pending", "running", "done", "merged"
FAILED, BLOCKED, CONFLICT = "failed", "blocked", "conflict"
STATUSES = frozenset({PENDING, RUNNING, DONE, MERGED, FAILED, BLOCKED, CONFLICT})
STUCK = frozenset({FAILED, BLOCKED, CONFLICT})  # nothing more happens to them until the coordinator replans

RESULT_DONE, RESULT_BLOCKED = "done", "blocked"
ITEM_RESULT_VALUES = (RESULT_DONE, RESULT_BLOCKED)

EXECUTOR_DEVICE, EXECUTOR_SEQUENTIAL = "device", "sequential"


class Executor(Protocol):
    """Runs a plan's items."""

    name: str

    def capacity(self, run: Any) -> int | None: ...

    async def start(self, db: Any, run: Any, item: SplitItem) -> dict[str, Any]: ...

    async def merge(self, db: Any, run: Any, item: SplitItem) -> None: ...

    async def finish(self, db: Any, run: Any) -> None: ...


def work_of(run: Any) -> WorkSplit:
    """The run's ``context.work`` (a copy; ``{}`` before a plan ran)."""
    value = dict(getattr(run, "context", None) or {}).get(WORK_KEY)
    return dict(value) if isinstance(value, dict) else {}  # type: ignore[return-value,typeddict-item]


def item_marker(session: Any) -> dict[str, Any] | None:
    marker = dict(getattr(session, "metadata_", None) or {}).get(ITEM_METADATA_KEY)
    return dict(marker) if isinstance(marker, dict) and marker.get("key") else None


def session_works_on(run: Any, item: SplitItem, session: Any) -> bool:
    """Whether ``session`` is ``item``'s session in ``run``: its thread, or a gateway session carrying its marker
    (a device item's Claude Code session). A session of an earlier iteration does not count."""
    if session is None or not item:
        return False
    if str(getattr(session, "id", "") or "") == str(item.get("session_id") or "~"):
        return True
    marker = item_marker(session) or {}
    iteration = marker.get("iteration")
    return (marker.get("run_id") == getattr(run, "id", None) and str(marker.get("key")) == str(item.get("id"))
            and (iteration is None or int(iteration) == int(item.get("iteration") or 1)))


def item_key_of(session: Any) -> str | None:
    marker = item_marker(session)
    return str(marker["key"]) if marker else None


__all__ = [
    "BLOCKED", "CONFLICT", "DONE", "EXECUTOR_DEVICE", "EXECUTOR_SEQUENTIAL", "Executor",
    "ExecutorName", "FAILED", "FixSource", "ITEM_METADATA_KEY", "ITEM_RESULT_VALUES", "ItemResult", "ItemStatus",
    "MERGED", "OUTPUT_KIND", "OUTPUT_TOOL", "PENDING", "RESULT_BLOCKED", "RESULT_DONE", "ROLE_ITEM", "ROUTES",
    "ROUTE_DONE", "ROUTE_REPLAN", "RUNNING", "ResultValue", "Route", "STATUSES", "STUCK", "SplitItem", "WORK_KEY",
    "WorkSplit", "item_key_of", "item_marker", "session_works_on", "work_of",
]
