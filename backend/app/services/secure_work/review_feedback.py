from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkCodingReviewEvent, WorkItem, WorkItemChangeUnit
from ..prompt_catalog import prompt_set_scope, render_prompt
from ..prompt_catalog.out_of_turn import prompt_set_for
from .cicd.cicd_findings import list_work_item_cicd_findings
from .cicd.cicd_pipeline_traces import list_work_item_cicd_pipeline_traces
from .coding_serializers import serialize_coding_review_event
from .external_activity_context import build_external_activity_context
from .jira_values import blank_to_none, object_value, optional_int
from .review_decision_record import (
    DECISION_RECORD_KEY,
    validated_decision_record,
    without_reserved_metadata,
)

EVENT_TYPES = {"inline_comment", "manual_edit", "diagnostic", "review_decision"}
SEVERITIES = {"info", "low", "medium", "high", "critical"}


async def list_coding_review_events(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    events = await _events_for_item(db, item.id)
    serialized = [serialize_coding_review_event(event) for event in events]
    # Read by agents outside a turn too (API, MCP): the instruction renders for the Work Item's Workspace.
    with prompt_set_scope(await prompt_set_for(db, workspace_id=getattr(item, "project_id", None))):
        feedback_context = build_agent_feedback_context(serialized)
    return {"items": serialized, "agent_feedback_context": feedback_context}


async def create_coding_review_event(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    # An explicit decision is validated against the plan and unit the reviewer saw before any write
    # (feedback without a decision returns None).
    decision_record = await validated_decision_record(db, item=item, current_user=current_user, payload=payload)
    change_unit_id = blank_to_none(payload.get("change_unit_id"))
    if change_unit_id:
        change_unit = await db.get(WorkItemChangeUnit, change_unit_id)
        if change_unit is None or change_unit.work_item_id != item.id:
            raise HTTPException(status_code=404, detail="Change Unit not found for this Work Item")
    event_type = str(payload.get("event_type") or "").strip()
    if event_type not in EVENT_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported review event type")
    file_path = str(payload.get("file_path") or "").strip()
    body = str(payload.get("body") or "").strip()
    # A decision covers the whole unit or item, not a file; comments and edits need a real file target.
    if not file_path and decision_record is None:
        raise HTTPException(status_code=422, detail="file_path is required")
    if not body and decision_record is None:
        raise HTTPException(status_code=422, detail="body is required")
    metadata = without_reserved_metadata(object_value(payload.get("metadata")))
    if decision_record is not None:
        metadata[DECISION_RECORD_KEY] = decision_record
    severity = blank_to_none(payload.get("severity"))
    if severity and severity not in SEVERITIES:
        raise HTTPException(status_code=422, detail="Unsupported severity")
    event = WorkCodingReviewEvent(
        work_item_id=item.id,
        change_unit_id=change_unit_id,
        event_type=event_type,
        file_path=file_path[:1000],
        line_number=optional_int(payload.get("line_number")),
        severity=severity,
        status=decision_record["decision"] if decision_record else str(payload.get("status") or "open").strip()[:80],
        body=body[:10000],
        original_content=_optional_text(payload.get("original_content"), limit=50000),
        updated_content=_optional_text(payload.get("updated_content"), limit=50000),
        metadata_json=metadata,
        agent_context_json=_agent_context_from_payload(payload),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(event)
    await db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.coding_review_event_created",
            resource_type="work_item",
            resource_id=item.id,
            details={
                "event_id": event.id,
                "event_type": event.event_type,
                "file_path": event.file_path,
                "change_unit_id": event.change_unit_id,
                "decision": decision_record["decision"] if decision_record else None,
            },
        )
    )
    await db.flush()
    return serialize_coding_review_event(event)


async def get_agent_feedback_context(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    payload = await list_coding_review_events(db, work_item_id)
    context = dict(payload["agent_feedback_context"])
    pipeline_payload = await list_work_item_cicd_pipeline_traces(db, work_item_id)
    finding_payload = await list_work_item_cicd_findings(db, work_item_id)
    context["cicd_failure_context"] = pipeline_payload["agent_failure_context"]
    context["cicd_findings_context"] = finding_payload["agent_failure_context"]
    with prompt_set_scope(await prompt_set_for(db, workspace_id=getattr(item, "project_id", None))):
        context["external_activity_context"] = build_external_activity_context(dict(item.source_fields_json or {}))
    return context


def build_agent_feedback_context(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    files: set[str] = set()
    human_edits: list[dict[str, Any]] = []
    reviewer_comments: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    constraints: list[str] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        counts[event_type] = counts.get(event_type, 0) + 1
        file_path = str(event.get("file_path") or "")
        if file_path:
            files.add(file_path)
        compact = _compact_event(event)
        if event_type == "manual_edit":
            human_edits.append(compact)
        elif event_type == "diagnostic":
            diagnostics.append(compact)
        else:
            reviewer_comments.append(compact)
        context = event.get("agent_context") if isinstance(event.get("agent_context"), dict) else {}
        constraint = str(context.get("constraint") or "").strip()
        if constraint:
            constraints.append(constraint)
    return {
        "event_count": len(events),
        "counts": counts,
        "changed_files": sorted(files),
        "human_edits": human_edits[:20],
        "reviewer_comments": reviewer_comments[:20],
        "diagnostics": diagnostics[:20],
        "constraints": constraints[:20],
        "agent_instruction": render_prompt("secure_work.review.feedback_instruction"),
    }


async def _get_work_item(db: AsyncSession, work_item_id: str) -> WorkItem:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return item


async def _events_for_item(db: AsyncSession, work_item_id: str) -> list[WorkCodingReviewEvent]:
    return (
        await db.execute(
            select(WorkCodingReviewEvent)
            .where(WorkCodingReviewEvent.work_item_id == work_item_id)
            .order_by(WorkCodingReviewEvent.created_at.asc())
        )
    ).scalars().all()


def _agent_context_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    context = object_value(payload.get("agent_context"))
    if context:
        return context
    return {
        "intent": blank_to_none(payload.get("body")),
        "source": "human_review",
        "must_preserve": bool(payload.get("event_type") == "manual_edit"),
    }


def _optional_text(value: Any, *, limit: int) -> str | None:
    text = blank_to_none(value)
    if text is None:
        return None
    return text[:limit]


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "type": event.get("event_type"),
        "file_path": event.get("file_path"),
        "line_number": event.get("line_number"),
        "severity": event.get("severity"),
        "body": event.get("body"),
        "status": event.get("status"),
        "has_updated_content": bool(event.get("updated_content")),
        "created_by": event.get("created_by"),
        "created_at": event.get("created_at"),
    }
