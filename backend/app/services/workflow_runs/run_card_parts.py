"""Parts of the run card (``views.run_view``): the task list, the model usage and the Spec Studio summary."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun


def task_list_view(run: WorkflowRun) -> list[dict[str, Any]]:
    """The work item's tasks for the run card, each with its status (``task_status``: open, in_progress, done,
    changes, verified) and, for ``changes``, the review finding as ``note``. ``done`` stays for the card's check mark:
    ``True`` for done or verified, ``False`` otherwise, ``None`` while a list without statuses has no known change."""
    from .task_list import missing_proofs, proofs_of, run_task_list
    from .task_status import DONE, OPEN, VERIFIED

    items = run_task_list(run)
    if not items:
        return []
    if not any("status" in item for item in items):
        context = dict(run.context or {})
        missing = missing_proofs(items, dict(context.get("device_change") or context.get("previous_device_change")
                                             or {}))
        open_ids = None if missing is None else {entry.split(" ", 1)[0] for entry in missing}
        return [{"id": item["id"], "text": item.get("text", ""), "proof": item.get("proof", ""), "status": OPEN,
                 "done": None if open_ids is None else item["id"] not in open_ids} for item in items]
    return [{"id": item["id"], "text": item.get("text", ""), "proof": item.get("proof", ""),
             "proofs": proofs_of(item), "status": item.get("status") or OPEN, "note": item.get("note"),
             "updated_at": item.get("updated_at"),
             "done": item.get("status") in (DONE, VERIFIED)} for item in items]


async def model_usage(db: AsyncSession, session_ids: list[str]) -> dict[str, Any]:
    """What the run's sessions spent on models: calls, tokens in and out, cost (weak models must not
    waste tokens — the number per run, and so per merged ticket, is visible)."""
    from sqlalchemy import func

    from ...models.runtime.audit import UsageEvent

    if not session_ids:
        return {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0}
    row = (await db.execute(
        select(func.count(), func.coalesce(func.sum(UsageEvent.tokens_in), 0),
               func.coalesce(func.sum(UsageEvent.tokens_out), 0), func.coalesce(func.sum(UsageEvent.cost), 0))
        .where(UsageEvent.session_id.in_(session_ids))
    )).one()
    return {"calls": int(row[0] or 0), "tokens_in": int(row[1] or 0), "tokens_out": int(row[2] or 0),
            "cost": round(float(row[3] or 0), 4)}


def spec_studio_summary(run: WorkflowRun) -> dict[str, Any] | None:
    """Whether the run has a Spec Studio and its state, for the run card's "Open Spec Studio"."""
    from .spec_studio.service import evaluate

    view = evaluate(run)
    if view is None:
        return None
    return {"version": view["version"], "open_points": len(view["open_points"]), "frozen": view["frozen"],
            "approved": len(view["approved"])}
