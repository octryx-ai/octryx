from __future__ import annotations

from typing import Any

from ...models import (
    WorkItem,
    WorkItemStateEvent,
    WorkItemSyncConfig,
    WorkItemSyncRun,
    WorkItemWorkflowDefinition,
    WorkPullRequest,
    WorkRepositoryProfile,
    WorkReviewerOverride,
)
from .automation_eligibility import work_item_automation_eligibility
from .jira.jira_item_details import work_item_detail_fields
from .jira_values import iso, optional_int


def serialize_sync_config(row: WorkItemSyncConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "project_id": row.project_id,
        "source_type": row.source_type,
        "source_instance": row.source_instance,
        "connector_name": row.connector_name,
        "connection_id": row.connection_id,
        "filters": dict(row.filters_json or {}),
        "field_mapping": dict(row.field_mapping_json or {}),
        "sync_options": dict(row.sync_options_json or {}),
        "is_active": bool(row.is_active),
        "last_sync_at": iso(row.last_sync_at),
        "last_sync_status": row.last_sync_status,
        "last_sync_summary": dict(row.last_sync_summary_json or {}),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_work_item(row: WorkItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "sync_config_id": row.sync_config_id,
        "source_type": row.source_type,
        "source_instance": row.source_instance,
        "source_id": row.source_id,
        "source_project_key": row.source_project_key,
        "source_key": row.source_key,
        "source_url": row.source_url,
        "title": row.title,
        "description": row.description or "",
        "issue_type": row.issue_type,
        "source_status": row.source_status,
        "priority": row.priority,
        "assignee": row.assignee,
        "reporter": row.reporter,
        "watchers": list(row.watchers_json or []),
        "labels": list(row.labels_json or []),
        "components": list(row.components_json or []),
        "fix_versions": list(row.fix_versions_json or []),
        "parent_key": row.parent_key,
        "epic_key": row.epic_key,
        "task_list": list(row.task_list or []),
        "linked_issues": list(row.linked_issues_json or []),
        "source_fields": dict(row.source_fields_json or {}),
        "automation_eligibility": work_item_automation_eligibility(row),
        "work_state": row.work_state,
        "sync_state": row.sync_state,
        "source_created_at": iso(row.source_created_at),
        "last_source_updated_at": iso(row.last_source_updated_at),
        "imported_at": iso(row.imported_at),
        "synced_at": iso(row.synced_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    } | work_item_detail_fields(row)  # people, comments, sprint/board, status mapping


def serialize_sync_run(row: WorkItemSyncRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "sync_config_id": row.sync_config_id,
        "triggered_by": row.triggered_by,
        # What started the run (``intake/runs.py`` records it); None when the summary carries none.
        "trigger": (row.summary_json or {}).get("trigger"),
        "mode": row.mode,
        "status": row.status,
        "limit": optional_int(row.limit),
        "query_preview": row.query_preview or "",
        "summary": dict(row.summary_json or {}),
        "sample_items": list(row.sample_items_json or []),
        "error": row.error,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "created_at": iso(row.created_at),
    }


def serialize_workflow_definition(row: WorkItemWorkflowDefinition) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "project_id": row.project_id,
        "states": list(row.states_json or []),
        "mappings": dict(row.mappings_json or {}),
        "sync_policy": dict(row.sync_policy_json or {}),
        "is_default": bool(row.is_default),
        "is_active": bool(row.is_active),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_state_event(row: WorkItemStateEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "workflow_id": row.workflow_id,
        "from_state": row.from_state,
        "to_state": row.to_state,
        "actor_id": row.actor_id,
        "reason": row.reason or "",
        "source": row.source,
        "dry_run": bool(row.dry_run),
        "jira_sync_preview": dict(row.jira_sync_preview_json or {}),
        "conflict": dict(row.conflict_json or {}),
        "created_at": iso(row.created_at),
    }


def serialize_transition_preview(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": bool(preview.get("valid")),
        "error": preview.get("error"),
        "workflow_id": preview.get("workflow_id"),
        "work_item_id": preview.get("work_item_id"),
        "source_key": preview.get("source_key"),
        "from_state": preview.get("from_state"),
        "to_state": preview.get("to_state"),
        "reason": preview.get("reason") or "",
        "jira_sync_preview": dict(preview.get("jira_sync_preview") or {}),
        "conflict": dict(preview.get("conflict") or {}),
    }


def serialize_repository_profile(row: WorkRepositoryProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "code_repository_id": row.code_repository_id,
        "technology_baseline_id": row.technology_baseline_id,
        "name": row.name,
        "provider": row.provider,
        "repository_url": row.repository_url,
        "default_branch": row.default_branch,
        "protected_branches": list(row.protected_branches_json or []),
        "jira_project_keys": list(row.jira_project_keys_json or []),
        "service_description": row.service_description or "",
        "owners": list(row.owners_json or []),
        "default_reviewers": list(row.default_reviewers_json or []),
        "branch_naming_rule": row.branch_naming_rule,
        "pr_target_branch": row.pr_target_branch,
        "required_pipelines": list(row.required_pipelines_json or []),
        "required_tests": list(row.required_tests_json or []),
        "setup_commands": list(row.setup_commands_json or []),
        "build_commands": list(row.build_commands_json or []),
        "test_commands": list(row.test_commands_json or []),
        "lint_commands": list(row.lint_commands_json or []),
        "format_commands": list(row.format_commands_json or []),
        "package_commands": list(row.package_commands_json or []),
        "local_run_commands": list(row.local_run_commands_json or []),
        "cleanup_commands": list(row.cleanup_commands_json or []),
        "builder_runtime_image": row.builder_runtime_image,
        "local_toolchain": list(row.local_toolchain_json or []),
        "required_env_vars": list(row.required_env_vars_json or []),
        "secret_references": list(row.secret_references_json or []),
        "protected_paths": list(row.protected_paths_json or []),
        "hotspot_files": list(row.hotspot_files_json or []),
        "artifact_paths": list(row.artifact_paths_json or []),
        "coverage_report_paths": list(row.coverage_report_paths_json or []),
        "test_report_paths": list(row.test_report_paths_json or []),
        "multi_repo_dependencies": list(row.multi_repo_dependencies_json or []),
        "risk_tags": list(row.risk_tags_json or []),
        "important_paths": list(row.important_paths_json or []),
        "profile_source": row.profile_source,
        "review_status": row.review_status,
        "is_active": bool(row.is_active),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_pull_request(row: WorkPullRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "change_unit_id": row.change_unit_id,
        "repository_profile_id": row.repository_profile_id,
        "provider": row.provider,
        "provider_instance": row.provider_instance,
        "project_key": row.project_key,
        "repository_slug": row.repository_slug,
        "repository_url": row.repository_url,
        "pr_id": row.pr_id,
        "pr_key": row.pr_key,
        "pr_url": row.pr_url,
        "title": row.title or "",
        "source_branch": row.source_branch,
        "target_branch": row.target_branch,
        "status": row.status,
        "author": dict(row.author_json or {}),
        "reviewers": list(row.reviewers_json or []),
        "approvals": list(row.approvals_json or []),
        "build_status": row.build_status,
        "mergeability": row.mergeability,
        "linked_jira_keys": list(row.linked_jira_keys_json or []),
        "mismatches": list(row.mismatch_json or []),
        "raw_summary": dict(row.raw_summary_json or {}),
        "source_created_at": iso(row.source_created_at),
        "source_updated_at": iso(row.source_updated_at),
        "last_synced_at": iso(row.last_synced_at),
        "refresh": {
            "status": row.refresh_status,
            "error_code": row.refresh_error_code,
            "error": row.refresh_error,
            "attempted_at": iso(row.refresh_attempted_at),
            "requested_at": iso(row.refresh_requested_at),
        },
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_reviewer_override(row: WorkReviewerOverride) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_item_id": row.work_item_id,
        "change_unit_id": row.change_unit_id,
        "selected_profile_id": row.selected_profile_id,
        "selected_reviewer": row.selected_reviewer,
        "reason": row.reason or "",
        "evidence": dict(row.evidence_json or {}),
        "actor_id": row.actor_id,
        "created_at": iso(row.created_at),
    }
