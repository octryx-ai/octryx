"""Workflows a platform service selects for the turn it starts itself.

Some turns are started by a governed platform service, not typed by a user: the secure-work
coding execution runs an approved Work Plan. That service knows its workflow, so it names it
on the ``TurnRequest`` (``platform_workflow_service``) instead of leaving the family to be
guessed from the prompt it wrote. The mapping (service -> workflow) is closed: only a listed
service selects, and only its listed workflow. HTTP routes never set the field.

The resolution shape mirrors the explicit-mode resolutions (same keys), with its own
``source``/``status`` so no consumer mistakes it for a published DB definition: it carries no
tool policy and no safety constraints, and it makes no workflow proposal call.
"""

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
    """A caller named a service outside the closed platform set (a programming error)."""


def platform_workflow_selection_resolution(service: str) -> dict[str, Any]:
    """The routing resolution for a platform service's own workflow selection."""
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
