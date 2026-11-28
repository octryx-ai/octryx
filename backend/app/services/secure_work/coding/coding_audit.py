from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    AuditLog,
    User,
    WorkCodingAuditEvent,
    WorkItem,
)
from ....time_utils import utc_now
from ..coding_serializers import (
    serialize_coding_audit_event,
)
from ..jira_values import blank_to_none, object_value
from ..serializers import serialize_work_item
from .audit_evidence_bundle import _evidence_bundle
from .audit_quality_gates import _dict_items, _gate_summary, _pr_summary, _quality_gates
from .audit_timeline import _audit_events, _timeline


async def create_coding_audit_event(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    event_type = _required_text(payload, "event_type", 100)
    title = _required_text(payload, "title", 300)
    row = WorkCodingAuditEvent(
        work_item_id=item.id,
        pipeline_run_id=blank_to_none(payload.get("pipeline_run_id")),
        pipeline_stage_id=blank_to_none(payload.get("pipeline_stage_id")),
        review_event_id=blank_to_none(payload.get("review_event_id")),
        event_type=event_type,
        title=title,
        summary=blank_to_none(payload.get("summary")),
        actor_kind=str(payload.get("actor_kind") or "user").strip()[:40],
        actor_id=blank_to_none(payload.get("actor_id")) or current_user.id,
        repository_name=blank_to_none(payload.get("repository_name")),
        branch_name=blank_to_none(payload.get("branch_name")),
        commit_sha=blank_to_none(payload.get("commit_sha")),
        pr_url=blank_to_none(payload.get("pr_url")),
        evidence_json=object_value(payload.get("evidence")),
        gate_results_json=_dict_items(payload.get("gate_results")),
        metadata_json=object_value(payload.get("metadata")),
        created_at=utc_now(),
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.coding_audit_event_created",
            resource_type="work_item",
            resource_id=item.id,
            project_id=item.project_id,
            details={"event_id": row.id, "event_type": row.event_type, "source_key": item.source_key},
        )
    )
    await db.flush()
    return serialize_coding_audit_event(row)


async def get_coding_audit_report(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    bundle = await _evidence_bundle(db, item)
    timeline = _timeline(bundle)
    gates = _quality_gates(bundle)
    summary = _pr_summary(bundle, gates)
    return {
        "work_item_id": item.id,
        "source_key": item.source_key,
        "timeline": timeline,
        "quality_gates": gates,
        "quality_summary": _gate_summary(gates),
        "pr_summary": summary,
        "evidence": {
            "work_item": serialize_work_item(item),
            "change_unit_count": len(bundle["change_units"]),
            "change_plan_count": len(bundle["change_plans"]),
            "review_event_count": len(bundle["review_events"]),
            "audit_event_count": len(bundle["audit_events"]),
            "pipeline_stage_count": len(bundle["pipeline_stages"]),
        },
    }


async def evaluate_coding_quality_gates(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = await get_coding_audit_report(db, work_item_id)
    item = await _get_work_item(db, work_item_id)
    row = WorkCodingAuditEvent(
        work_item_id=item.id,
        event_type="quality_gate_evaluation",
        title="PR quality gates evaluated",
        summary=f"{report['quality_summary']['status']} ({report['quality_summary']['blocking']} blocking gates)",
        actor_kind="user",
        actor_id=current_user.id,
        evidence_json=object_value((payload or {}).get("evidence")),
        gate_results_json=report["quality_gates"],
        metadata_json={"source": "secure_work_quality_gate_api"},
        created_at=utc_now(),
    )
    db.add(row)
    await db.flush()
    report["audit_event"] = serialize_coding_audit_event(row)
    report["timeline"] = sorted(
        [*report["timeline"], *_audit_events([row])],
        key=lambda event: event.get("created_at") or "",
    )
    report["evidence"]["audit_event_count"] = int(report["evidence"].get("audit_event_count") or 0) + 1
    return report


async def _get_work_item(db: AsyncSession, work_item_id: str) -> WorkItem:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return item


def _required_text(payload: dict[str, Any], key: str, limit: int) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value[:limit]
