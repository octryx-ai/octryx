"""Deterministic Change Plan content built from the Work Item, its change units and reviewer recommendations."""

from __future__ import annotations

from typing import Any

from ....models import (
    WorkItem,
    WorkItemChangeUnit,
    WorkItemWorkflowDefinition,
)
from ..jira_values import string_list
from ..plan_serializers import serialize_change_unit
from ..reviewers import MISSING_OWNERS
from .acceptance_coverage import (
    derive_unit_acceptance_criteria,
    normalize_acceptance_criteria,
)


def _plan_data_from_inputs(
    *,
    item: WorkItem,
    units: list[WorkItemChangeUnit],
    reviewer_payload: dict[str, Any],
    workflow: WorkItemWorkflowDefinition | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    change_units = [serialize_change_unit(unit) for unit in units]
    affected_repositories = _affected_repositories(item, change_units)
    validation_plan = _validation_plan(change_units, payload)
    acceptance_criteria = normalize_acceptance_criteria(
        payload.get("acceptance_criteria")
    ) or derive_unit_acceptance_criteria(change_units)
    security_risks = _security_risks(item, change_units, reviewer_payload)
    open_questions = _open_questions(change_units, reviewer_payload)
    reviewer_recommendations = list(reviewer_payload.get("recommendations") or [])[:5]
    return {
        "understood_request": str(
            payload.get("understood_request")
            or f"{item.source_key}: {item.title}. {item.description or 'No Jira description captured.'}"
        ).strip(),
        "assumptions": string_list(payload.get("assumptions")) or _default_assumptions(item, workflow),
        "open_questions": string_list(payload.get("open_questions")) or open_questions,
        "affected_repositories": affected_repositories,
        "change_units": change_units,
        "proposed_branches": [
            {"repository_name": unit["repository_name"], "branch_name": unit["branch_name"]}
            for unit in change_units
        ],
        "planned_files": [
            {"repository_name": unit["repository_name"], "paths": unit.get("expected_paths") or []}
            for unit in change_units
        ],
        "validation_plan": validation_plan,
        "acceptance_criteria": acceptance_criteria,
        "security_risks": security_risks,
        "reviewer_recommendations": reviewer_recommendations,
        "required_approvals": _required_approvals(change_units, reviewer_recommendations),
        "expected_prs": _expected_prs(change_units),
        "rollback_plan": str(
            payload.get("rollback_plan")
            or (
                "Revert or close the planned PRs, restore the previous deployed revision, "
                "and rerun the listed validation commands."
            )
        ).strip(),
        "trace_refs": _trace_refs(payload),
        "evidence": _evidence(item, change_units, reviewer_payload, workflow),
    }


def _affected_repositories(item: WorkItem, change_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "repository_name": unit["repository_name"],
            "repository_profile_id": unit.get("repository_profile_id"),
            "scope": unit.get("scope") or item.title,
            "status": unit.get("status"),
            "target_branch": _target_branch(unit),
            "protected_paths": list((unit.get("reviewer_policy") or {}).get("protected_paths") or []),
            "hotspot_files": list((unit.get("reviewer_policy") or {}).get("hotspot_files") or []),
            "command_profile": dict((unit.get("reviewer_policy") or {}).get("command_profile") or {}),
            "missing_profile_fields": unit.get("missing_profile_fields") or [],
        }
        for unit in change_units
    ]


def _expected_prs(change_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "repository_name": unit["repository_name"],
            "target_branch": _target_branch(unit),
            "source_branch": unit["branch_name"],
            "status": "expected",
        }
        for unit in change_units
    ]


def _default_assumptions(item: WorkItem, workflow: WorkItemWorkflowDefinition | None) -> list[str]:
    values = [
        "No repository files will be changed before this Change Plan is approved.",
        "Jira remains the source of truth for task status and sprint metadata.",
    ]
    if workflow:
        values.append(f"Work Item state changes use workflow '{workflow.name}'.")
    if item.fix_versions_json:
        values.append(f"Target fix version is {', '.join(str(value) for value in item.fix_versions_json)}.")
    return values


def _validation_plan(change_units: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    requested = string_list(payload.get("validation_plan"))
    if requested:
        return [{"command": command, "source": "manual"} for command in requested]
    commands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in change_units:
        for command in unit.get("validation_commands") or []:
            text = str(command).strip()
            if text and text not in seen:
                seen.add(text)
                commands.append(
                    {
                        "command": text,
                        "repository_name": unit["repository_name"],
                        "source": "repository_profile",
                    }
                )
    return commands or [{"command": "Manual verification required", "source": "manual_required"}]


def _security_risks(
    item: WorkItem,
    change_units: list[dict[str, Any]],
    reviewer_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    labels = {str(value).lower() for value in [*(item.labels_json or []), *(item.components_json or [])]}
    if labels.intersection({"security", "runtime", "policy", "agent"}):
        risks.append({"severity": "high", "risk": "Security/runtime relevant Jira labels require explicit approval."})
    for unit in change_units:
        missing = unit.get("missing_profile_fields") or []
        if missing:
            risks.append(
                {
                    "severity": "medium",
                    "risk": f"Repository profile for {unit['repository_name']} is incomplete.",
                    "missing_profile_fields": missing,
                }
            )
    if reviewer_payload.get("missing_setup"):
        risks.append(
            {
                "severity": "medium",
                "risk": "Reviewer recommendation setup is incomplete.",
                "missing_setup": list(reviewer_payload.get("missing_setup") or []),
            }
        )
    return risks


def _open_questions(change_units: list[dict[str, Any]], reviewer_payload: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    if not change_units:
        questions.append("Which repository or repositories should this Work Item change?")
    if MISSING_OWNERS in set(reviewer_payload.get("missing_setup") or []):
        questions.append(
            "Who owns or reviews the affected repositories? Set them in Settings → Workspace → Repositories."
        )
    for unit in change_units:
        if unit.get("missing_profile_fields"):
            questions.append(f"Complete repository profile metadata for {unit['repository_name']}.")
    return questions


def _required_approvals(
    change_units: list[dict[str, Any]],
    reviewer_recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    approvals = [{"type": "change_plan", "required": True, "reason": "Code-changing execution requires plan approval."}]
    for unit in change_units:
        reviewers = list((unit.get("reviewer_policy") or {}).get("required_reviewers") or [])
        defaults = list((unit.get("reviewer_policy") or {}).get("default_reviewers") or [])
        approvals.append(
            {
                "type": "code_review",
                "repository_name": unit["repository_name"],
                "required": True,
                "reviewers": reviewers or defaults,
            }
        )
    if reviewer_recommendations:
        approvals.append(
            {
                "type": "recommended_reviewer",
                "required": False,
                "reviewers": [entry["display_name"] for entry in reviewer_recommendations[:3]],
            }
        )
    return approvals


def _target_branch(unit: dict[str, Any]) -> str:
    policy = unit.get("reviewer_policy") or {}
    target = policy.get("target_branch")
    return str(target or "configured default").strip()


def _trace_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs = payload.get("trace_refs")
    if isinstance(refs, list):
        return [entry for entry in refs if isinstance(entry, dict)]
    return []


def _evidence(
    item: WorkItem,
    change_units: list[dict[str, Any]],
    reviewer_payload: dict[str, Any],
    workflow: WorkItemWorkflowDefinition | None,
) -> dict[str, Any]:
    return {
        "work_item": {
            "source_type": item.source_type,
            "source_instance": item.source_instance,
            "source_key": item.source_key,
            "source_status": item.source_status,
            "work_state": item.work_state,
            "labels": list(item.labels_json or []),
            "components": list(item.components_json or []),
            "fix_versions": list(item.fix_versions_json or []),
        },
        "change_unit_count": len(change_units),
        "reviewer_recommendation_count": len(reviewer_payload.get("recommendations") or []),
        "workflow": {"id": workflow.id, "name": workflow.name} if workflow else None,
        "repository_command_profiles": [
            {
                "repository_name": unit["repository_name"],
                "repository_profile_id": unit.get("repository_profile_id"),
                "commands": dict((unit.get("reviewer_policy") or {}).get("command_profile") or {}),
                "validation_commands": list(unit.get("validation_commands") or []),
                "protected_paths": list((unit.get("reviewer_policy") or {}).get("protected_paths") or []),
                "hotspot_files": list((unit.get("reviewer_policy") or {}).get("hotspot_files") or []),
                "missing_profile_fields": list(unit.get("missing_profile_fields") or []),
            }
            for unit in change_units
        ],
    }
