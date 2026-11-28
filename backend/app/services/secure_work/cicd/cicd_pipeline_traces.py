from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    AuditLog,
    User,
    WorkCicdPipelineTrace,
    WorkCicdProviderConfig,
    WorkItem,
    WorkRepositoryProfile,
)
from ...prompt_catalog import prompt_set_scope, render_prompt
from ...prompt_catalog.out_of_turn import prompt_set_for
from ..cicd_serializers import serialize_cicd_pipeline_trace
from ..jira_values import blank_to_none, object_value, parse_datetime
from ..related_rows import CICD_PROVIDER, REPOSITORY_PROFILE, load_optional_related

FAILURE_TYPES = {
    "compile_failure",
    "unit_test_failure",
    "integration_failure",
    "security_finding",
    "deployment_failure",
    "infra_failure",
    "flaky",
    "unknown",
}
FAILED_STATUSES = {"failed", "failure", "error", "aborted", "blocked", "unstable"}
PASSED_STATUSES = {"passed", "pass", "success", "succeeded", "ok"}
RUNNING_STATUSES = {"running", "in_progress", "building", "queued", "pending"}
STAGE_LOG_LIMIT = 2000
TRACE_LOG_LIMIT = 5000
AGENT_CONTEXT_LIMIT = 6500
MAX_STAGES = 80
MAX_ARTIFACTS = 80
MAX_REPORTS = 40


async def list_work_item_cicd_pipeline_traces(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    rows = (
        await db.execute(
            select(WorkCicdPipelineTrace)
            .where(WorkCicdPipelineTrace.work_item_id == work_item_id)
            .order_by(WorkCicdPipelineTrace.created_at.desc())
        )
    ).scalars().all()
    items = [serialize_cicd_pipeline_trace(row) for row in rows]
    # Read by agents outside a turn too (API, MCP): the instruction renders for the Work Item's Workspace.
    with prompt_set_scope(await prompt_set_for(db, workspace_id=getattr(item, "project_id", None))):
        failure_context = build_pipeline_failure_context(items)
    return {"items": items, "agent_failure_context": failure_context}


async def record_work_item_cicd_pipeline_trace(
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
    repository_profile = await load_optional_related(
        db, current_user, REPOSITORY_PROFILE, blank_to_none(payload.get("repository_profile_id")),
        for_workspace=item.project_id,
    )
    normalized = _normalize_trace_payload(
        payload,
        provider=provider,
        repository_profile=repository_profile,
    )
    trace = WorkCicdPipelineTrace(
        work_item_id=item.id,
        provider_config_id=provider.id if provider else None,
        repository_profile_id=repository_profile.id if repository_profile else None,
        created_by=current_user.id,
        updated_by=current_user.id,
        **normalized,
    )
    db.add(trace)
    await db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.cicd_pipeline_trace_recorded",
            resource_type="secure_work_cicd",
            resource_id=trace.id,
            project_id=item.project_id,
            details={
                "work_item_id": item.id,
                "provider_config_id": trace.provider_config_id,
                "job_name": trace.job_name,
                "status": trace.status,
                "failure_type": (trace.failure_summary_json or {}).get("primary_failure_type"),
            },
        )
    )
    await db.flush()
    return serialize_cicd_pipeline_trace(trace)


def build_pipeline_failure_context(traces: list[dict[str, Any]]) -> dict[str, Any]:
    failed_stages: list[dict[str, Any]] = []
    for trace in traces:
        for stage in trace.get("stages") or []:
            if _is_failed_status(str(stage.get("status") or "")):
                failed_stages.append(_compact_failed_stage(trace, stage))
    context = {
        "failure_count": len(failed_stages),
        "failed_stages": failed_stages[:12],
        "agent_instruction": render_prompt("secure_work.cicd.failure_instruction"),
    }
    return _bound_agent_context(context)


def _normalize_trace_payload(
    payload: dict[str, Any],
    *,
    provider: WorkCicdProviderConfig | None,
    repository_profile: WorkRepositoryProfile | None,
) -> dict[str, Any]:
    raw_stages = payload.get("stages") if isinstance(payload.get("stages"), list) else []
    stages = [_normalize_stage(stage, index) for index, stage in enumerate(raw_stages[:MAX_STAGES])]
    artifacts = _artifact_list(payload.get("artifacts"))
    test_reports = _report_list(payload.get("test_reports") or payload.get("test_report"))
    scan_reports = _report_list(payload.get("scan_reports") or payload.get("scan_report"))
    coverage = object_value(payload.get("coverage"))
    log_excerpt = _log_excerpt(
        payload.get("logs") or payload.get("log") or payload.get("log_excerpt"),
        limit=TRACE_LOG_LIMIT,
    )
    failure_summary = _failure_summary(
        stages,
        scan_reports=scan_reports,
        test_reports=test_reports,
        log_excerpt=log_excerpt,
    )
    agent_context = _agent_context(
        {
            "job_name": _first_text(payload.get("job_name")),
            "build_number": _first_text(payload.get("build_number")),
            "status": _normalize_status(payload.get("status")),
            "failure_summary": failure_summary,
            "failed_stages": [
                _compact_failed_stage({}, stage)
                for stage in stages
                if _is_failed_status(stage["status"])
            ],
        }
    )
    return {
        "job_name": _first_text(payload.get("job_name"), required=True)[:500],
        "job_url": _first_text(payload.get("job_url")),
        "build_number": _first_text(payload.get("build_number")),
        "build_url": _first_text(payload.get("build_url")),
        "provider_type": (
            _first_text(payload.get("provider_type"), provider.provider_type if provider else None) or "generic"
        ),
        "branch_name": _first_text(payload.get("branch_name")),
        "commit_sha": _first_text(payload.get("commit_sha")),
        "pr_url": _first_text(payload.get("pr_url")),
        "status": _normalize_status(payload.get("status")),
        "result": _first_text(payload.get("result")),
        "triggered_by": _first_text(payload.get("triggered_by")),
        "trigger_actor": _first_text(payload.get("trigger_actor"), payload.get("actor")),
        "deployment_target": _first_text(payload.get("deployment_target")),
        "started_at": parse_datetime(payload.get("started_at")),
        "completed_at": parse_datetime(payload.get("completed_at")),
        "duration_ms": _optional_positive_int(payload.get("duration_ms")),
        "stages_json": stages,
        "log_excerpt_json": log_excerpt,
        "artifacts_json": artifacts,
        "test_reports_json": test_reports,
        "coverage_json": coverage,
        "scan_reports_json": scan_reports,
        "failure_summary_json": failure_summary,
        "agent_context_json": agent_context,
        "metadata_json": _redact_secrets(object_value(payload.get("metadata"))),
    }


def _normalize_stage(stage: Any, index: int) -> dict[str, Any]:
    raw = object_value(stage)
    key = _first_text(raw.get("stage_key"), raw.get("key"), raw.get("name")) or f"stage-{index + 1}"
    label = _first_text(raw.get("label"), raw.get("name"), key) or key
    log_excerpt = _log_excerpt(raw.get("logs") or raw.get("log") or raw.get("log_excerpt"), limit=STAGE_LOG_LIMIT)
    artifacts = _artifact_list(raw.get("artifacts"))
    test_report = object_value(raw.get("test_report"))
    scan_report = object_value(raw.get("scan_report"))
    coverage = object_value(raw.get("coverage"))
    status = _normalize_status(raw.get("status") or raw.get("result"))
    failure_type = _failure_type(raw, log_excerpt=log_excerpt, test_report=test_report, scan_report=scan_report)
    return {
        "stage_key": key[:120],
        "label": label[:220],
        "stage_order": _optional_positive_int(raw.get("stage_order")) if raw.get("stage_order") is not None else index,
        "status": status,
        "result": _first_text(raw.get("result")),
        "failure_type": failure_type if _is_failed_status(status) else None,
        "started_at": _iso_or_none(raw.get("started_at")),
        "completed_at": _iso_or_none(raw.get("completed_at")),
        "duration_ms": _optional_positive_int(raw.get("duration_ms")),
        "log_excerpt": log_excerpt,
        "artifacts": artifacts,
        "test_report": test_report,
        "coverage": coverage,
        "scan_report": scan_report,
        "evidence": _object_list(raw.get("evidence")),
        "metadata": _redact_secrets(object_value(raw.get("metadata"))),
    }


def _failure_summary(
    stages: list[dict[str, Any]],
    *,
    scan_reports: list[dict[str, Any]],
    test_reports: list[dict[str, Any]],
    log_excerpt: dict[str, Any],
) -> dict[str, Any]:
    failed = [stage for stage in stages if _is_failed_status(stage["status"])]
    counts: dict[str, int] = {}
    for stage in failed:
        failure_type = str(stage.get("failure_type") or "unknown")
        counts[failure_type] = counts.get(failure_type, 0) + 1
    if not failed and scan_reports:
        counts["security_finding"] = counts.get("security_finding", 0) + 1
    if not failed and _test_report_has_failures(test_reports):
        counts["unit_test_failure"] = counts.get("unit_test_failure", 0) + 1
    primary = next((key for key, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)), None)
    return {
        "failed_stage_count": len(failed),
        "primary_failure_type": primary,
        "failure_type_counts": counts,
        "first_failed_stage": failed[0]["stage_key"] if failed else None,
        "log_truncated": bool(log_excerpt.get("truncated")),
    }


def _failure_type(
    stage: dict[str, Any],
    *,
    log_excerpt: dict[str, Any],
    test_report: dict[str, Any],
    scan_report: dict[str, Any],
) -> str:
    explicit = str(stage.get("failure_type") or "").strip()
    if explicit in FAILURE_TYPES:
        return explicit
    text = " ".join(
        [
            str(stage.get("stage_key") or ""),
            str(stage.get("label") or ""),
            str(stage.get("status") or ""),
            str(stage.get("result") or ""),
            str(log_excerpt.get("text") or ""),
            str(test_report),
            str(scan_report),
        ]
    ).lower()
    if any(marker in text for marker in ("flaky", "rerun passed", "unstable")):
        return "flaky"
    if any(marker in text for marker in ("trivy", "vulnerability", "cve-", "sast", "secret scan", "security")):
        return "security_finding"
    if _test_report_has_failures([test_report]) or any(
        marker in text for marker in ("pytest", "junit", "surefire", "unit test")
    ):
        return "unit_test_failure"
    if any(marker in text for marker in ("integration", "failsafe", "docker compose", "integration test")):
        return "integration_failure"
    if any(marker in text for marker in ("compile", "compilation", "javac", "maven compiler", "tsc", "typecheck")):
        return "compile_failure"
    if any(marker in text for marker in ("deploy", "helm", "kubectl", "rollout", "release failed")):
        return "deployment_failure"
    if any(
        marker in text
        for marker in ("agent lost", "executor", "timeout", "network", "imagepull", "node unavailable")
    ):
        return "infra_failure"
    return "unknown"


def _log_excerpt(value: Any, *, limit: int) -> dict[str, Any]:
    text = _text_from_log(value)
    if not text:
        return {"text": "", "truncated": False, "original_length": 0, "limit": limit}
    redacted = _redact_text(text)
    truncated = len(redacted) > limit
    if truncated:
        head = redacted[: limit // 2]
        tail = redacted[-(limit // 2) :]
        redacted = f"{head}\n...[truncated]...\n{tail}"
    return {"text": redacted, "truncated": truncated, "original_length": len(text), "limit": limit}


def _agent_context(value: dict[str, Any]) -> dict[str, Any]:
    return _bound_agent_context(
        {
            **value,
            "context_budget_chars": AGENT_CONTEXT_LIMIT,
            "source": "cicd_pipeline_trace",
        }
    )


def _bound_agent_context(value: dict[str, Any]) -> dict[str, Any]:
    text = _redact_text(str(value))
    if len(text) <= AGENT_CONTEXT_LIMIT:
        return value
    return {
        "truncated": True,
        "context_budget_chars": AGENT_CONTEXT_LIMIT,
        "preview": text[:AGENT_CONTEXT_LIMIT],
    }


async def _get_work_item(db: AsyncSession, work_item_id: str) -> WorkItem:
    row = await db.get(WorkItem, work_item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return row


def _normalize_status(value: Any) -> str:
    status = str(value or "unknown").strip().lower().replace(" ", "_")
    if status in PASSED_STATUSES:
        return "passed"
    if status in RUNNING_STATUSES:
        return "running"
    if status in FAILED_STATUSES:
        return "failed" if status != "unstable" else "unstable"
    return status[:80] or "unknown"


def _is_failed_status(status: str) -> bool:
    return status in {"failed", "error", "aborted", "blocked", "unstable"}


def _artifact_list(value: Any) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for item in _object_list(value)[:MAX_ARTIFACTS]:
        artifacts.append(
            _redact_secrets(
                {
                    "name": _first_text(item.get("name"), item.get("file_name"), item.get("fileName")),
                    "relative_path": _first_text(item.get("relative_path"), item.get("relativePath"), item.get("path")),
                    "url": _first_text(item.get("url")),
                    "size_bytes": _optional_positive_int(item.get("size_bytes") or item.get("size")),
                    "content_type": _first_text(item.get("content_type"), item.get("mime_type")),
                    "kind": _first_text(item.get("kind"), item.get("type")),
                }
            )
        )
    return artifacts


def _report_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [_redact_secrets(value)]
    return [_redact_secrets(item) for item in _object_list(value)[:MAX_REPORTS]]


def _object_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _test_report_has_failures(reports: list[dict[str, Any]]) -> bool:
    for report in reports:
        for key in ("fail_count", "failCount", "failed", "failures", "error_count", "errors"):
            parsed = _optional_positive_int(report.get(key))
            if parsed and parsed > 0:
                return True
    return False


def _compact_failed_stage(trace: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
    log_excerpt = stage.get("log_excerpt") if isinstance(stage.get("log_excerpt"), dict) else {}
    return {
        "trace_id": trace.get("id"),
        "job_name": trace.get("job_name"),
        "build_number": trace.get("build_number"),
        "build_url": trace.get("build_url"),
        "stage_key": stage.get("stage_key"),
        "label": stage.get("label"),
        "status": stage.get("status"),
        "failure_type": stage.get("failure_type") or "unknown",
        "log_excerpt": _redact_text(str(log_excerpt.get("text") or ""))[:1200],
        "artifacts": (stage.get("artifacts") or [])[:5],
    }


def _text_from_log(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or value.get("log") or "")
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value or "")


def _first_text(*values: Any, required: bool = False) -> str | None:
    for value in values:
        text = blank_to_none(value)
        if text is not None:
            return text
    if required:
        raise HTTPException(status_code=422, detail="job_name is required")
    return None


def _optional_positive_int(value: Any) -> int | None:
    if value in {None, ""} or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _iso_or_none(value: Any) -> str | None:
    parsed = parse_datetime(value)
    return parsed.isoformat() if parsed else None


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[redacted]" if _secret_key(key) else _redact_secrets(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    text = re.sub(r"(?i)\b(bearer)\s+[a-z0-9._~+/=-]{12,}", r"\1 [redacted]", text)
    text = re.sub(r"(?i)\b(password|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", text)
    return text


def _secret_key(key: Any) -> bool:
    normalized = str(key).lower()
    return any(marker in normalized for marker in ("password", "token", "secret", "api_key", "apikey"))
