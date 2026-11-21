"""Run lists beyond one card: the extras of Work › Runs rows and the run's events and decisions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun, WorkflowRunDecision, WorkflowRunEvent
from ...models.runtime.secure_work import WorkItem
from .views import STEP_KINDS, _iso, _pause, run_nodes

MAX_EVENTS = 200


async def work_extras(db: AsyncSession, runs: list[WorkflowRun]) -> dict[str, dict[str, Any]]:
    """What Work › Runs shows per row beyond ``run_row``: the step with its
    place among the phases, the pause facts, the pull request and the model cost. One cost query for all rows; a
    workflow version's graph is parsed once."""
    from ..operations.costs import RunCost, run_cost_split

    # One cost rule with Operations (``operations/costs``): the API cost, and apart from it the seat calls' API
    # equivalent at list price, never added together.
    costs = await run_cost_split(db, [run.id for run in runs])
    item_ids = sorted({run.work_item_id for run in runs if run.work_item_id})
    items = {row.id: {"key": row.source_key, "title": row.title} for row in (await db.execute(
        select(WorkItem).where(WorkItem.id.in_(item_ids)))).scalars()} if item_ids else {}
    graphs: dict[str, list[dict[str, Any]]] = {}
    extras: dict[str, dict[str, Any]] = {}
    for run in runs:
        # A graph is shared by every run of its version.
        key = f"version:{run.flow_definition_version_id or run.id}"
        if key not in graphs:
            graphs[key] = await run_nodes(db, run)
        nodes = graphs[key]
        phases = [node for node in nodes if node["kind"] in STEP_KINDS]
        current = next((node for node in nodes if node["id"] == run.current_node_id), None)
        index = next((i for i, node in enumerate(phases) if node["id"] == run.current_node_id), None)
        pr = dict(run.pull_request or {})
        extras[run.id] = {
            "step": {"title": current["title"] if current else None, "kind": current["kind"] if current else None,
                     "index": index + 1 if index is not None else None, "total": len(phases)},
            "pause": _pause(run),
            "pull_request": ({"id": pr.get("id"), "url": pr.get("url"), "state": pr.get("state")}
                             if pr.get("url") or pr.get("id") else None),
            "cost": round((costs.get(run.id) or RunCost()).api_usd, 4),
            "seat_api_equivalent": round((costs.get(run.id) or RunCost()).seat_api_equivalent_usd, 4),
            "seat_unpriced_calls": (costs.get(run.id) or RunCost()).seat_unpriced_calls,
            "work_item": items.get(run.work_item_id or ""),
        }
    return extras


async def run_events(db: AsyncSession, run: WorkflowRun, *, user: Any = None) -> list[dict[str, Any]]:
    """The run's events and decisions; a fragment checksum is shown only to a platform ``user``."""
    from .fragments.provenance import is_platform_admin, redact_event_detail
    from .review.artefact_projection import event_detail

    events = (await db.execute(
        select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id)
        .order_by(WorkflowRunEvent.created_at.asc(), WorkflowRunEvent.id.asc()).limit(MAX_EVENTS)
    )).scalars().all()
    decisions = (await db.execute(
        select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id)
        .order_by(WorkflowRunDecision.created_at.asc())
    )).scalars().all()
    admin = any("fragment" in dict(item.detail or {}) or "composition" in dict(item.detail or {})
                for item in events) and await is_platform_admin(db, user)
    return {
        "events": [{"id": item.id, "kind": item.kind, "node_id": item.node_id,
                    "detail": redact_event_detail(item.kind, event_detail(item.kind, dict(item.detail or {})),
                                                  admin=admin),
                    "actor_id": item.actor_id, "created_at": _iso(item.created_at)} for item in events],
        "decisions": [{"id": item.id, "node_id": item.node_id, "kind": item.kind, "subject": item.subject,
                       "action": item.action, "payload_hash": item.payload_hash, "approval_id": item.approval_id,
                       "decided_by": item.decided_by, "created_at": _iso(item.created_at)} for item in decisions],
    }
