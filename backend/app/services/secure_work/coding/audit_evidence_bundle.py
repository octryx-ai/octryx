"""The evidence bundle a coding audit report and its quality gates are computed from."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    WorkChangePlan,
    WorkCodingAuditEvent,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
    WorkCodingReviewEvent,
    WorkItem,
    WorkItemChangeUnit,
    WorkReviewerOverride,
)
from ..plans.redeclare import SUPERSEDED_UNIT_STATUS
from .coding_gate_evidence import (
    collect_recorded_gate_evidence,
    load_native_ci_findings,
)
from .coding_review_evidence import evaluate_reviewer_gate, load_reviewer_identities


async def _evidence_bundle(db: AsyncSession, item: WorkItem) -> dict[str, Any]:
    change_plans = (
        await db.execute(
            select(WorkChangePlan)
            .where(WorkChangePlan.work_item_id == item.id)
            .order_by(WorkChangePlan.version.desc())
        )
    ).scalars().all()
    change_units = (
        await db.execute(
            select(WorkItemChangeUnit)
            .where(
                WorkItemChangeUnit.work_item_id == item.id,
                WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
            )
            .order_by(WorkItemChangeUnit.dependency_order.asc())
        )
    ).scalars().all()
    review_events = (
        await db.execute(
            select(WorkCodingReviewEvent)
            .where(WorkCodingReviewEvent.work_item_id == item.id)
            .order_by(WorkCodingReviewEvent.created_at.asc())
        )
    ).scalars().all()
    audit_events = (
        await db.execute(
            select(WorkCodingAuditEvent)
            .where(WorkCodingAuditEvent.work_item_id == item.id)
            .order_by(WorkCodingAuditEvent.created_at.asc())
        )
    ).scalars().all()
    reviewer_overrides = (
        await db.execute(
            select(WorkReviewerOverride)
            .where(WorkReviewerOverride.work_item_id == item.id)
            .order_by(WorkReviewerOverride.created_at.asc())
        )
    ).scalars().all()
    run, stages = await _latest_pipeline_run(db, item)
    bundle = {
        "item": item,
        "source_fields": dict(item.source_fields_json or {}),
        "change_plans": change_plans,
        "change_units": change_units,
        "review_events": review_events,
        "audit_events": audit_events,
        "reviewer_overrides": reviewer_overrides,
        "pipeline_run": run,
        "pipeline_stages": stages,
        "cicd_findings": await load_native_ci_findings(db, item.id),
    }
    # Explicit recorded gate outcomes only; plans and free text are never evidence.
    bundle["recorded_gate_evidence"] = collect_recorded_gate_evidence(bundle)
    # Explicit review decisions only; identities come from two batched queries.
    bundle["reviewer_gate"] = evaluate_reviewer_gate(bundle, await load_reviewer_identities(db, bundle))
    return bundle


async def _latest_pipeline_run(
    db: AsyncSession, item: WorkItem
) -> tuple[WorkCodingPipelineRun | None, list[WorkCodingPipelineStage]]:
    run = (
        await db.execute(
            select(WorkCodingPipelineRun)
            .where(WorkCodingPipelineRun.work_item_id == item.id)
            .order_by(WorkCodingPipelineRun.started_at.desc())
        )
    ).scalars().first()
    stages = []
    if run:
        stages = (
            await db.execute(
                select(WorkCodingPipelineStage)
                .where(WorkCodingPipelineStage.run_id == run.id)
                .order_by(WorkCodingPipelineStage.stage_order.asc())
            )
        ).scalars().all()
    return run, stages
