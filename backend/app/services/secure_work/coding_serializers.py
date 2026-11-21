"""API views of coding pipelines, coding workspaces and the coding review and audit events."""

from __future__ import annotations

from typing import Any

from ...models import (
    WorkCodingAuditEvent,
    WorkCodingPipelineConfig,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
    WorkCodingReviewEvent,
    WorkCodingWorkspace,
)
from .jira_values import iso


def serialize_coding_pipeline_config(row: WorkCodingPipelineConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "project_id": row.project_id,
        "scope": dict(row.scope_json or {}),
        "stages": list(row.stages_json or []),
        "required_stage_keys": list(row.required_stage_keys_json or []),
        "controls": dict(row.controls_json or {}),
        "checks": list(dict(row.controls_json or {}).get("checks") or []),
        "review_status": row.review_status,
        "is_active": bool(row.is_active),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_coding_pipeline_run(
    row: WorkCodingPipelineRun,
    stages: list[WorkCodingPipelineStage] | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "config_id": row.config_id,
        "status": row.status,
        "current_stage_key": row.current_stage_key,
        "control_state": row.control_state,
        "summary": dict(row.summary_json or {}),
        "recovery_state": dict(row.recovery_state_json or {}),
        "stages": [serialize_coding_pipeline_stage(stage) for stage in stages or []],
        "started_by": row.started_by,
        "updated_by": row.updated_by,
        "started_at": iso(row.started_at),
        "updated_at": iso(row.updated_at),
        "completed_at": iso(row.completed_at),
    }


def serialize_coding_pipeline_stage(row: WorkCodingPipelineStage) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "stage_key": row.stage_key,
        "label": row.label,
        "stage_order": row.stage_order,
        "status": row.status,
        "required": bool(row.required),
        "inputs": dict(row.inputs_json or {}),
        "outputs": dict(row.outputs_json or {}),
        "evidence": list(row.evidence_json or []),
        "required_actions": list(row.required_actions_json or []),
        "policy_refs": list(row.policy_refs_json or []),
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_coding_workspace(row: WorkCodingWorkspace) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "pipeline_run_id": row.pipeline_run_id,
        "change_unit_id": row.change_unit_id,
        "repository_profile_id": row.repository_profile_id,
        "session_id": row.session_id,
        "provider": row.provider,
        "provider_instance": row.provider_instance,
        "project_key": row.project_key,
        "repository_name": row.repository_name,
        "repository_slug": row.repository_slug,
        "repository_url": row.repository_url,
        "base_branch": row.base_branch,
        "resolved_base_branch": row.resolved_base_branch,
        "feature_branch": row.feature_branch,
        "base_commit": row.base_commit,
        "workspace_path": row.workspace_path,
        "source_repository_root": row.source_repository_root,
        "source_evidence_cutoff": iso(row.source_evidence_cutoff),
        "restart_generation": int(row.restart_generation or 0),
        "status": row.status,
        "evidence": dict(row.evidence_json or {}),
        "is_active": bool(row.is_active),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_coding_review_event(row: WorkCodingReviewEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "change_unit_id": row.change_unit_id,
        "event_type": row.event_type,
        "file_path": row.file_path,
        "line_number": row.line_number,
        "severity": row.severity,
        "status": row.status,
        "body": row.body,
        "original_content": row.original_content,
        "updated_content": row.updated_content,
        "metadata": dict(row.metadata_json or {}),
        "agent_context": dict(row.agent_context_json or {}),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_coding_audit_event(row: WorkCodingAuditEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "pipeline_run_id": row.pipeline_run_id,
        "pipeline_stage_id": row.pipeline_stage_id,
        "review_event_id": row.review_event_id,
        "event_type": row.event_type,
        "title": row.title,
        "summary": row.summary or "",
        "actor_kind": row.actor_kind,
        "actor_id": row.actor_id,
        "repository_name": row.repository_name,
        "branch_name": row.branch_name,
        "commit_sha": row.commit_sha,
        "pr_url": row.pr_url,
        "evidence": dict(row.evidence_json or {}),
        "gate_results": list(row.gate_results_json or []),
        "metadata": dict(row.metadata_json or {}),
        "created_at": iso(row.created_at),
    }
