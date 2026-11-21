"""Reviewer-only Coding summary for the Coding session list.

The list gets the same verdict the coding audit's ``reviewer_approval`` gate shows, from the same
evaluator (``evaluate_reviewer_gate``) with the same inputs: the plans latest first, the active
Change Units, the Work Item's review events and reviewer overrides. Inputs are loaded once for all
listed (already workspace-scoped) Work Items, so the query count does not grow with the rows; no
per-row audit, pipeline or CI loading.

The summary is the work review only. It is not Work Plan approval, execution authorization or
pull-request readiness (``ready_to_open_pr`` needs every audit gate). Failures are not caught here:
a database error fails the list request instead of hiding the verdict.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkChangePlan, WorkCodingReviewEvent, WorkItemChangeUnit, WorkReviewerOverride
from ..plans.redeclare import SUPERSEDED_UNIT_STATUS
from .coding_review_evidence import evaluate_reviewer_gate, load_reviewer_identities_for

REVIEW_SUMMARY_BASIS = "reviewer_approval"


async def review_summaries_for_items(
    db: AsyncSession,
    item_ids: list[str],
    plans_by_item: dict[str, list[WorkChangePlan]],
    units_by_item: dict[str, list[WorkItemChangeUnit]],
) -> dict[str, dict[str, Any]]:
    """Reviewer verdict per Work Item id; ``plans_by_item`` lists each item's plans latest first."""
    if not item_ids:
        return {}
    events_by_item: dict[str, list[WorkCodingReviewEvent]] = defaultdict(list)
    for event in (
        await db.execute(
            select(WorkCodingReviewEvent)
            .where(WorkCodingReviewEvent.work_item_id.in_(item_ids))
            .order_by(WorkCodingReviewEvent.created_at.asc())
        )
    ).scalars():
        events_by_item[event.work_item_id].append(event)
    overrides_by_item: dict[str, list[WorkReviewerOverride]] = defaultdict(list)
    for override in (
        await db.execute(
            select(WorkReviewerOverride)
            .where(WorkReviewerOverride.work_item_id.in_(item_ids))
            .order_by(WorkReviewerOverride.created_at.asc())
        )
    ).scalars():
        overrides_by_item[override.work_item_id].append(override)
    bundles = {
        item_id: {
            "change_plans": list(plans_by_item.get(item_id, [])),
            # The audit bundle's unit set: every Change Unit that is not superseded.
            "change_units": [unit for unit in units_by_item.get(item_id, []) if unit.status != SUPERSEDED_UNIT_STATUS],
            "review_events": events_by_item[item_id],
            "reviewer_overrides": overrides_by_item[item_id],
        }
        for item_id in item_ids
    }
    identities = await load_reviewer_identities_for(db, list(bundles.values()))
    return {item_id: _summary(evaluate_reviewer_gate(bundle, identities)) for item_id, bundle in bundles.items()}


def _summary(gate: dict[str, Any]) -> dict[str, Any]:
    evidence = gate["evidence"]
    return {
        "basis": REVIEW_SUMMARY_BASIS,
        "status": gate["status"],
        "blocking": gate["status"] == "block",
        "reason": gate["reason"],
        "plan_id": evidence.get("plan_id"),
        "plan_version": evidence.get("plan_version"),
    }
