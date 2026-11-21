"""API views of Change Plans, their decisions and their change units."""

from __future__ import annotations

from typing import Any

from ...models import (
    WorkChangePlan,
    WorkChangePlanDecision,
    WorkItemChangeUnit,
)
from .jira_values import iso, optional_int


def serialize_change_unit(row: WorkItemChangeUnit) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "repository_profile_id": row.repository_profile_id,
        "repository_name": row.repository_name,
        "branch_name": row.branch_name,
        "scope": row.scope or "",
        "expected_paths": list(row.expected_paths_json or []),
        "validation_commands": list(row.validation_commands_json or []),
        "reviewer_policy": dict(row.reviewer_policy_json or {}),
        "pr_link": row.pr_link,
        "dependency_order": optional_int(row.dependency_order) or 0,
        "status": row.status,
        "missing_profile_fields": list(row.missing_profile_fields_json or []),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_change_plan(row: WorkChangePlan) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "workflow_id": row.workflow_id,
        "supersedes_plan_id": row.supersedes_plan_id,
        "version": int(row.version or 0),
        "status": row.status,
        "title": row.title,
        "understood_request": row.understood_request or "",
        "assumptions": list(row.assumptions_json or []),
        "open_questions": list(row.open_questions_json or []),
        "affected_repositories": list(row.affected_repositories_json or []),
        "change_units": list(row.change_units_json or []),
        "proposed_branches": list(row.proposed_branches_json or []),
        "planned_files": list(row.planned_files_json or []),
        "validation_plan": list(row.validation_plan_json or []),
        "acceptance_criteria": list(row.acceptance_criteria_json or []),
        "security_risks": list(row.security_risks_json or []),
        "reviewer_recommendations": list(row.reviewer_recommendations_json or []),
        "required_approvals": list(row.required_approvals_json or []),
        "expected_prs": list(row.expected_prs_json or []),
        "rollback_plan": row.rollback_plan or "",
        "trace_refs": list(row.trace_refs_json or []),
        "evidence": dict(row.evidence_json or {}),
        "jira_sync_preview": dict(row.jira_sync_preview_json or {}),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "approved_by": row.approved_by,
        "decided_by": row.decided_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        "approved_at": iso(row.approved_at),
        "decided_at": iso(row.decided_at),
    }


def serialize_change_plan_decision(row: WorkChangePlanDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "change_plan_id": row.change_plan_id,
        "work_item_id": row.work_item_id,
        "actor_id": row.actor_id,
        "action": row.action,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "reason": row.reason or "",
        "required_changes": list(row.required_changes_json or []),
        "jira_sync_preview": dict(row.jira_sync_preview_json or {}),
        "evidence": dict(row.evidence_json or {}),
        "created_at": iso(row.created_at),
    }
