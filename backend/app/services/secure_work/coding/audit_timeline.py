"""The chronological coding audit timeline: plans, units, pipeline stages, reviews and audit events."""

from __future__ import annotations

from typing import Any

from ....models import (
    WorkChangePlan,
    WorkCodingAuditEvent,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
    WorkCodingReviewEvent,
    WorkItem,
    WorkItemChangeUnit,
)
from ..coding_serializers import (
    serialize_coding_audit_event,
    serialize_coding_pipeline_run,
    serialize_coding_pipeline_stage,
    serialize_coding_review_event,
)
from ..plan_serializers import serialize_change_plan, serialize_change_unit


def _timeline(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    item: WorkItem = bundle["item"]
    events = [
        {
            "id": f"work-item-{item.id}",
            "kind": "work_item",
            "title": f"{item.source_key} imported",
            "summary": item.title,
            "status": item.work_state,
            "created_at": item.imported_at.isoformat() if item.imported_at else None,
            "evidence": {"source_status": item.source_status, "assignee": item.assignee},
        }
    ]
    events.extend(_change_plan_events(bundle["change_plans"]))
    events.extend(_change_unit_events(bundle["change_units"]))
    events.extend(_pipeline_events(bundle["pipeline_run"], bundle["pipeline_stages"]))
    events.extend(_review_events(bundle["review_events"]))
    events.extend(_audit_events(bundle["audit_events"]))
    return sorted(events, key=lambda event: event.get("created_at") or "")


def _change_plan_events(plans: list[WorkChangePlan]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"change-plan-{plan.id}",
            "kind": "change_plan",
            "title": f"Change Plan v{plan.version}: {plan.status}",
            "summary": plan.understood_request or plan.title,
            "status": plan.status,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "evidence": serialize_change_plan(plan),
        }
        for plan in plans
    ]


def _change_unit_events(units: list[WorkItemChangeUnit]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"change-unit-{unit.id}",
            "kind": "change_unit",
            "title": f"{unit.repository_name} / {unit.branch_name}",
            "summary": unit.scope or "Repository change unit",
            "status": unit.status,
            "created_at": unit.created_at.isoformat() if unit.created_at else None,
            "evidence": serialize_change_unit(unit),
        }
        for unit in units
    ]


def _pipeline_events(run: WorkCodingPipelineRun | None, stages: list[WorkCodingPipelineStage]) -> list[dict[str, Any]]:
    if not run:
        return []
    events = [
        {
            "id": f"pipeline-run-{run.id}",
            "kind": "pipeline_run",
            "title": f"Coding pipeline {run.status}",
            "summary": f"Current stage: {run.current_stage_key or 'complete'}",
            "status": run.status,
            "created_at": run.started_at.isoformat() if run.started_at else None,
            "evidence": serialize_coding_pipeline_run(run, stages),
        }
    ]
    events.extend(
        {
            "id": f"pipeline-stage-{stage.id}",
            "kind": "pipeline_stage",
            "title": stage.label,
            "summary": stage.stage_key,
            "status": stage.status,
            "created_at": (stage.completed_at or stage.started_at or stage.created_at).isoformat(),
            "evidence": serialize_coding_pipeline_stage(stage),
        }
        for stage in stages
    )
    return events


def _review_events(events: list[WorkCodingReviewEvent]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"review-event-{event.id}",
            "kind": "review_event",
            "title": event.event_type.replace("_", " ").title(),
            "summary": event.body,
            "status": event.status,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "evidence": serialize_coding_review_event(event),
        }
        for event in events
    ]


def _audit_events(events: list[WorkCodingAuditEvent]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"audit-event-{event.id}",
            "kind": "audit_event",
            "title": event.title,
            "summary": event.summary or event.event_type,
            "status": "recorded",
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "evidence": serialize_coding_audit_event(event),
        }
        for event in events
    ]
