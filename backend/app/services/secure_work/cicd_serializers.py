"""API views of CI/CD builds, pipeline traces and findings."""

from __future__ import annotations

from typing import Any

from ...models import (
    WorkCicdBuild,
    WorkCicdFinding,
    WorkCicdPipelineTrace,
)
from .jira_values import iso


def serialize_cicd_build(row: WorkCicdBuild) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider_config_id": row.provider_config_id,
        "work_item_id": row.work_item_id,
        "pipeline_run_id": row.pipeline_run_id,
        "pipeline_stage_id": row.pipeline_stage_id,
        "repository_profile_id": row.repository_profile_id,
        "job_name": row.job_name,
        "job_url": row.job_url,
        "build_number": row.build_number,
        "build_url": row.build_url,
        "status": row.status,
        "result": row.result,
        "branch_name": row.branch_name,
        "commit_sha": row.commit_sha,
        "pr_url": row.pr_url,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "duration_ms": row.duration_ms,
        "triggered_by": row.triggered_by,
        "cause": row.cause,
        "logs_ref": row.logs_ref,
        "artifacts": list(row.artifacts_json or []),
        "test_report": dict(row.test_report_json or {}),
        "metadata": dict(row.metadata_json or {}),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_cicd_pipeline_trace(row: WorkCicdPipelineTrace) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider_config_id": row.provider_config_id,
        "work_item_id": row.work_item_id,
        "repository_profile_id": row.repository_profile_id,
        "job_name": row.job_name,
        "job_url": row.job_url,
        "build_number": row.build_number,
        "build_url": row.build_url,
        "provider_type": row.provider_type,
        "branch_name": row.branch_name,
        "commit_sha": row.commit_sha,
        "pr_url": row.pr_url,
        "status": row.status,
        "result": row.result,
        "triggered_by": row.triggered_by,
        "trigger_actor": row.trigger_actor,
        "deployment_target": row.deployment_target,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "duration_ms": row.duration_ms,
        "stages": list(row.stages_json or []),
        "log_excerpt": dict(row.log_excerpt_json or {}),
        "artifacts": list(row.artifacts_json or []),
        "test_reports": list(row.test_reports_json or []),
        "coverage": dict(row.coverage_json or {}),
        "scan_reports": list(row.scan_reports_json or []),
        "failure_summary": dict(row.failure_summary_json or {}),
        "agent_context": dict(row.agent_context_json or {}),
        "metadata": dict(row.metadata_json or {}),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_cicd_finding(row: WorkCicdFinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "provider_config_id": row.provider_config_id,
        "pipeline_trace_id": row.pipeline_trace_id,
        "finding_type": row.finding_type,
        "status": row.status,
        "event_status": row.event_status,
        "severity": row.severity,
        "title": row.title,
        "summary": row.summary,
        "job_name": row.job_name,
        "build_number": row.build_number,
        "build_url": row.build_url,
        "branch_name": row.branch_name,
        "commit_sha": row.commit_sha,
        "pr_url": row.pr_url,
        "current_for_commit": bool(row.current_for_commit),
        "stale_reason": row.stale_reason,
        "artifacts": list(row.artifacts_json or []),
        "comments": list(row.comments_json or []),
        "evidence": dict(row.evidence_json or {}),
        "gate_results": list(row.gate_results_json or []),
        "metadata": dict(row.metadata_json or {}),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
