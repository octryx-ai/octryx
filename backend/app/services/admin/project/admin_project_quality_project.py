"""Project payload serialization for admin project quality views."""

from __future__ import annotations

from app.services.design_artifact.common import list_recommended_design_artifacts

from ....models import Project
from ...design_delivery_sync import get_project_design_trace_sync_workflows, list_design_trace_sync_templates
from ...runtime_policy_bundle import apply_runtime_policy_bundle, normalize_runtime_policy_config


def serialize_project(project: Project) -> dict[str, object]:
    config = dict(project.config or {}) if isinstance(project.config, dict) else {}
    repo_code_quality = config.get("repo_code_quality")
    projected = apply_runtime_policy_bundle(config)
    repository_bootstrap = config.get("repository_bootstrap")
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "is_active": bool(project.is_active),
        "source_type": project.source_type or "manual",
        "template_key": project.template_key,
        "template_version": project.template_version,
        "template_metadata": project.template_metadata if isinstance(project.template_metadata, dict) else {},
        "is_system": bool(project.is_system),
        "repo_code_quality": repo_code_quality if isinstance(repo_code_quality, dict) else {},
        "repository_bootstrap": repository_bootstrap if isinstance(repository_bootstrap, dict) else {},
        "runtime_policy": normalize_runtime_policy_config(
            config.get("runtime_policy") if isinstance(config.get("runtime_policy"), dict) else {}
        ),
        "effective_runtime_policy": projected.get("effective_runtime_policy")
        if isinstance(projected.get("effective_runtime_policy"), dict)
        else {},
        "project_agent_catalog": [],
        "project_agent_role_summary": [],
        "code_repositories": [],
        "design_artifacts": [],
        "design_artifact_templates": list_recommended_design_artifacts(),
        "design_readiness": _empty_design_readiness(),
        "design_traceability": _empty_design_traceability(),
        "design_trace_sync_templates": list_design_trace_sync_templates(),
        "design_trace_sync_workflows": get_project_design_trace_sync_workflows(config),
        "design_trace_sync_custom_templates": [],
        "design_trace_sync_tasks": [],
        "design_trace_sync_schedulers": [],
    }


def _empty_design_readiness() -> dict[str, object]:
    return {
        "required_total": 0,
        "approved_required_total": 0,
        "required_approval_rate": 0.0,
        "readiness_score": 0,
        "missing_required_kinds": [],
        "pending_required_kinds": [],
        "approved_required_kinds": [],
        "blockers": [],
        "artifact_coverage": {},
        "repository_traceability": {
            "total_repositories": 0,
            "linked_repositories": 0,
            "linked_repository_ids": [],
            "coverage_rate": 0.0,
        },
    }


def _empty_design_traceability() -> dict[str, object]:
    return {
        "total_links": 0,
        "artifacts_total": 0,
        "artifacts_linked": 0,
        "approved_artifacts_total": 0,
        "approved_artifacts_linked": 0,
        "approved_trace_rate": 0.0,
        "traceability_score": 0,
        "link_counts_by_type": {},
        "blockers": [],
        "task_options": [],
        "items": [],
    }
