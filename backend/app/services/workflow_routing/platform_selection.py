"""Workflows a platform service selects for the turn it starts itself."""

from __future__ import annotations

from typing import Any

PLATFORM_WORKFLOW_SELECTION_SOURCE = "platform_service"
PLATFORM_WORKFLOW_SELECTION_STATUS = "selected"

SECURE_WORK_CODING_EXECUTION = "secure_work_coding_execution"
# Service -> the one workflow it may select for its own turns.
PLATFORM_WORKFLOWS: dict[str, str] = {
    SECURE_WORK_CODING_EXECUTION: "coding_change_tdd",
}


class UnknownPlatformWorkflowServiceError(ValueError):
    pass


def platform_workflow_selection_resolution(service: str) -> dict[str, Any]:
    clean_service = str(service or "").strip()
    clean_workflow_id = PLATFORM_WORKFLOWS.get(clean_service)
    if not clean_workflow_id:
        raise UnknownPlatformWorkflowServiceError(f"{clean_service!r} is not a platform workflow service.")
    return {
        "source": PLATFORM_WORKFLOW_SELECTION_SOURCE,
        "status": PLATFORM_WORKFLOW_SELECTION_STATUS,
        "selection_source": clean_service,
        "workflow_key": None,
        "unmatched_reason": None,
        "fallback_reason": None,
        "workflow_id": clean_workflow_id,
        "workflow_class": clean_workflow_id,
        "policy_id": None,
        "policy_version_id": None,
        "priority": None,
        "matched_group_id": None,
        # The governed coding run never lands on a weak runtime (R3).
        "workflow_contract": {
            "workflow_id": clean_workflow_id,
            "workflow_class": clean_workflow_id,
            "required_model_capability": "coding",
        },
        "tool_policy": None,
        "safety_constraints": None,
    }


__all__ = [
    "PLATFORM_WORKFLOWS",
    "PLATFORM_WORKFLOW_SELECTION_SOURCE",
    "PLATFORM_WORKFLOW_SELECTION_STATUS",
    "SECURE_WORK_CODING_EXECUTION",
    "UnknownPlatformWorkflowServiceError",
    "platform_workflow_selection_resolution",
]
