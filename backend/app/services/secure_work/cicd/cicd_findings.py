from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    AuditLog,
    User,
    WorkCicdFinding,
    WorkCicdPipelineTrace,
    WorkCicdProviderConfig,
    WorkCodingAuditEvent,
    WorkItem,
    WorkItemStateEvent,
)
from ....time_utils import utc_now
from ...prompt_catalog import prompt_set_scope, render_prompt
from ...prompt_catalog.out_of_turn import prompt_set_for
from ..cicd_serializers import serialize_cicd_finding
from ..jira_values import blank_to_none, object_value
from ..related_rows import CICD_PROVIDER, PIPELINE_TRACE, load_optional_related

PASSING_STATUSES = {"passed", "pass", "success", "succeeded", "ok", "completed"}
FAILING_STATUSES = {"failed", "failure", "error", "blocked", "aborted", "unstable"}
RERUN_STATUSES = {"rerun", "rerun_requested", "retry", "retry_requested"}
CURRENT_STATUS = "current"
STALE_STATUS = "stale_ignored"
TERMINAL_WORK_STATES = {"done", "completed", "cancelled", "canceled", "rejected", "superseded"}
MAX_LIST_ITEMS = 500


async def list_work_item_cicd_findings(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    rows = (
        await db.execute(
            select(WorkCicdFinding)
            .where(WorkCicdFinding.work_item_id == work_item_id)
            .order_by(WorkCicdFinding.created_at.desc())
            .limit(MAX_LIST_ITEMS)
        )
    ).scalars().all()
    items = [serialize_cicd_finding(row) for row in rows]
    # Read by agents outside a turn too (API, MCP): the instruction renders for the Work Item's Workspace.
    with prompt_set_scope(await prompt_set_for(db, workspace_id=getattr(item, "project_id", None))):
        failure_context = _agent_failure_context(items)
    return {
        "items": items,
        "summary": _summary(items),
        "agent_failure_context": failure_context,
    }


async def record_work_item_cicd_finding(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    provider = await load_optional_related(
        db, current_user, CICD_PROVIDER, blank_to_none(payload.get("provider_config_id")),
        for_workspace=item.project_id,
    )
    trace = await load_optional_related(
        db, current_user, PIPELINE_TRACE,
        blank_to_none(payload.get("pipeline_trace_id") or payload.get("cicd_pipeline_trace_id")),
        for_workspace=item.project_id,
    )
    normalized = _normalize_payload(payload, trace=trace)
    stale_reason = _stale_reason(item, normalized, payload)
    if stale_reason:
        normalized["status"] = STALE_STATUS
        normalized["current_for_commit"] = False
        normalized["stale_reason"] = stale_reason
    row = WorkCicdFinding(
        work_item_id=item.id,
        provider_config_id=_provider_id(provider=provider, trace=trace),
        pipeline_trace_id=trace.id if trace else None,
        created_by=current_user.id,
        updated_by=current_user.id,
        **normalized,
    )
    db.add(row)
    await db.flush()

    state_transition = await _apply_current_finding(db, item, row, current_user)
    audit_event = _audit_event(row, current_user=current_user, state_transition=state_transition)
    db.add(audit_event)
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.cicd_finding_recorded",
            resource_type="secure_work_cicd_finding",
            resource_id=row.id,
            details={
                "work_item_id": item.id,
                "source_key": item.source_key,
                "status": row.status,
                "event_status": row.event_status,
                "state_transition": state_transition,
            },
        )
    )
    await db.flush()
    result = serialize_cicd_finding(row)
    result["audit_event_id"] = audit_event.id
    result["state_transition"] = state_transition
    return result


async def _apply_current_finding(
    db: AsyncSession,
    item: WorkItem,
    finding: WorkCicdFinding,
    current_user: User,
) -> dict[str, Any] | None:
    if finding.status == STALE_STATUS:
        return None
    _merge_source_fields(item, finding)
    if finding.event_status not in FAILING_STATUSES:
        return None
    previous = item.work_state
    if previous in TERMINAL_WORK_STATES or previous == "needs_remediation":
        return None
    item.work_state = "needs_remediation"
    event = WorkItemStateEvent(
        work_item_id=item.id,
        workflow_id=None,
        from_state=previous,
        to_state=item.work_state,
        actor_id=current_user.id,
        reason=f"CI/CD finding requires remediation: {finding.title}",
        source="cicd_finding",
        dry_run=False,
        jira_sync_preview_json={"mode": "local_only", "will_mutate_jira": False},
        conflict_json={},
        created_at=utc_now(),
    )
    db.add(event)
    await db.flush()
    return {"from_state": previous, "to_state": item.work_state, "event_id": event.id}


def _normalize_payload(
    payload: dict[str, Any],
    *,
    trace: WorkCicdPipelineTrace | None,
) -> dict[str, Any]:
    event_status = _normalize_event_status(
        payload.get("event_status")
        or payload.get("status")
        or payload.get("result")
        or (trace.status if trace else None)
    )
    title = _required_text(payload, "title", default=_default_title(event_status, payload, trace), limit=300)
    return {
        "finding_type": _short_text(payload.get("finding_type") or _finding_type(event_status), 80),
        "status": CURRENT_STATUS,
        "event_status": event_status,
        "severity": _severity(payload.get("severity"), event_status),
        "title": title,
        "summary": blank_to_none(payload.get("summary")),
        "job_name": _first_text(
            payload.get("job_name"),
            trace.job_name if trace else None,
        ),
        "build_number": _first_text(
            payload.get("build_number"),
            trace.build_number if trace else None,
        ),
        "build_url": _first_text(
            payload.get("build_url"),
            trace.build_url if trace else None,
        ),
        "branch_name": _first_text(
            payload.get("branch_name"),
            trace.branch_name if trace else None,
        ),
        "commit_sha": _first_text(
            payload.get("commit_sha"),
            trace.commit_sha if trace else None,
        ),
        "pr_url": _first_text(payload.get("pr_url"), trace.pr_url if trace else None),
        "current_for_commit": True,
        "stale_reason": None,
        "artifacts_json": _object_list(
            payload.get("artifacts")
            or (trace.artifacts_json if trace else None)
        ),
        "comments_json": _object_list(payload.get("comments")),
        "evidence_json": _redact_secrets(object_value(payload.get("evidence"))),
        "gate_results_json": _gate_results(event_status, payload),
        "metadata_json": _redact_secrets(object_value(payload.get("metadata"))),
    }


def _stale_reason(item: WorkItem, normalized: dict[str, Any], payload: dict[str, Any]) -> str | None:
    if payload.get("is_latest_for_commit") is False:
        return "Payload marked the run as not latest for its commit."
    superseded_by = _first_text(payload.get("superseded_by_commit_sha"))
    if superseded_by:
        return f"Run superseded by commit {superseded_by}."
    commit_sha = normalized.get("commit_sha")
    if not commit_sha:
        return None
    source_fields = dict(item.source_fields_json or {})
    current_commit = _first_text(
        source_fields.get("current_commit_sha"),
        source_fields.get("latest_commit_sha"),
        source_fields.get("head_commit_sha"),
    )
    if current_commit and current_commit != commit_sha:
        return f"Run commit {commit_sha} does not match current commit {current_commit}."
    return None


def _merge_source_fields(item: WorkItem, finding: WorkCicdFinding) -> None:
    source_fields = dict(item.source_fields_json or {})
    compact = {
        "id": finding.id,
        "title": finding.title,
        "status": finding.event_status,
        "job_name": finding.job_name,
        "build_number": finding.build_number,
        "commit_sha": finding.commit_sha,
        "branch_name": finding.branch_name,
        "pr_url": finding.pr_url,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
    }
    source_fields["ci_status"] = finding.event_status
    source_fields["latest_ci_finding"] = compact
    source_fields["ci_findings"] = [compact, *_list_value(source_fields.get("ci_findings"))][:25]
    source_fields["ci_runs"] = [compact, *_list_value(source_fields.get("ci_runs"))][:25]
    item.source_fields_json = source_fields


def _audit_event(
    finding: WorkCicdFinding,
    *,
    current_user: User,
    state_transition: dict[str, Any] | None,
) -> WorkCodingAuditEvent:
    return WorkCodingAuditEvent(
        work_item_id=finding.work_item_id,
        event_type="cicd_finding",
        title=finding.title,
        summary=finding.summary or _audit_summary(finding),
        actor_kind="system",
        actor_id=current_user.id,
        branch_name=finding.branch_name,
        commit_sha=finding.commit_sha,
        pr_url=finding.pr_url,
        evidence_json={
            "finding": serialize_cicd_finding(finding),
            "state_transition": state_transition,
        },
        gate_results_json=finding.gate_results_json,
        metadata_json={"source": "cicd_findings", "finding_status": finding.status},
        created_at=utc_now(),
    )


def _gate_results(event_status: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("gate_results"):
        return [dict(item) for item in _object_list(payload.get("gate_results"))]
    if event_status in PASSING_STATUSES:
        status = "pass"
        reason = "Required CI/CD pipeline passed."
    elif event_status in FAILING_STATUSES:
        status = "block"
        reason = "Required CI/CD pipeline failed."
    elif event_status in RERUN_STATUSES:
        status = "review_required"
        reason = "CI/CD pipeline rerun was requested."
    else:
        status = "review_required"
        reason = "CI/CD pipeline status needs review."
    return [{"key": "ci_status", "status": status, "reason": reason, "evidence": {}}]


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        event_counts[item["event_status"]] = event_counts.get(item["event_status"], 0) + 1
    return {"total": len(items), "counts": counts, "event_counts": event_counts}


def _agent_failure_context(items: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [
        {
            "title": item["title"],
            "summary": item.get("summary"),
            "job_name": item.get("job_name"),
            "build_number": item.get("build_number"),
            "build_url": item.get("build_url"),
            "commit_sha": item.get("commit_sha"),
            "stale": item["status"] == STALE_STATUS,
        }
        for item in items
        if item["event_status"] in FAILING_STATUSES
    ]
    return {
        "failure_count": len(failures),
        "failed_findings": failures[:12],
        "agent_instruction": render_prompt("secure_work.cicd.findings_instruction"),
    }


async def _get_work_item(db: AsyncSession, work_item_id: str) -> WorkItem:
    row = await db.get(WorkItem, work_item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return row


def _normalize_event_status(value: Any) -> str:
    status = str(value or "unknown").strip().lower().replace(" ", "_")
    if status in PASSING_STATUSES:
        return "passed"
    if status in FAILING_STATUSES:
        return "failed" if status != "unstable" else "unstable"
    if status in RERUN_STATUSES:
        return "rerun_requested"
    if status in {"running", "in_progress", "building", "queued", "pending"}:
        return "running"
    return status[:80] or "unknown"


def _severity(value: Any, event_status: str) -> str:
    explicit = str(value or "").strip().lower()
    if explicit in {"info", "low", "medium", "high", "critical"}:
        return explicit
    if event_status in FAILING_STATUSES:
        return "high"
    if event_status in RERUN_STATUSES:
        return "medium"
    return "info"


def _finding_type(event_status: str) -> str:
    if event_status in FAILING_STATUSES:
        return "failure"
    if event_status in PASSING_STATUSES:
        return "success"
    if event_status in RERUN_STATUSES:
        return "rerun"
    return "status_update"


def _default_title(
    event_status: str,
    payload: dict[str, Any],
    trace: WorkCicdPipelineTrace | None,
) -> str:
    job_name = _first_text(
        payload.get("job_name"),
        trace.job_name if trace else None,
    )
    build_number = _first_text(
        payload.get("build_number"),
        trace.build_number if trace else None,
    )
    target = " ".join(value for value in [job_name, f"#{build_number}" if build_number else ""] if value)
    return f"CI/CD {event_status.replace('_', ' ')}{f': {target}' if target else ''}"


def _audit_summary(finding: WorkCicdFinding) -> str:
    parts = [finding.event_status]
    if finding.job_name:
        parts.append(finding.job_name)
    if finding.build_number:
        parts.append(f"#{finding.build_number}")
    if finding.status == STALE_STATUS and finding.stale_reason:
        parts.append(f"ignored: {finding.stale_reason}")
    return " · ".join(parts)


def _provider_id(
    *,
    provider: WorkCicdProviderConfig | None,
    trace: WorkCicdPipelineTrace | None,
) -> str | None:
    if provider:
        return provider.id
    if trace:
        return trace.provider_config_id
    return None


def _required_text(payload: dict[str, Any], key: str, *, default: str, limit: int) -> str:
    value = str(payload.get(key) or default or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value[:limit]


def _short_text(value: Any, limit: int) -> str:
    return str(value or "").strip().lower().replace(" ", "_")[:limit]


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_redact_secrets(object_value(item)) for item in value if isinstance(item, dict)]


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _redact_secrets(value: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, current in value.items():
        if any(marker in key.lower() for marker in ("token", "password", "secret", "credential", "api_key")):
            redacted[key] = "[redacted]"
        elif isinstance(current, dict):
            redacted[key] = _redact_secrets(current)
        elif isinstance(current, list):
            redacted[key] = [_redact_secrets(item) if isinstance(item, dict) else item for item in current]
        else:
            redacted[key] = current
    return redacted
