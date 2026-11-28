"""Parts of the run card (``views.run_view``): the task list, the model usage and the Spec Studio summary."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun


def task_list_view(run: WorkflowRun) -> list[dict[str, Any]]:
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
    from .spec_studio.service import evaluate

    view = evaluate(run)
    if view is None:
        return None
    return {"version": view["version"], "open_points": len(view["open_points"]), "frozen": view["frozen"],
            "approved": len(view["approved"])}
