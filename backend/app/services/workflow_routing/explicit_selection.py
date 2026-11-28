"""Explicit workflow selection: a chat turn's ``workflow_key`` -> an explicit state."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..project_activity import PROJECT_INACTIVE, project_is_inactive
from ..run_admission.phased_catalog import published_phased_workflows

EXPLICIT_WORKFLOW_SELECTION_SOURCE = "explicit_workflow_key"
EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY = "unknown_key"


async def list_published_workflow_definitions(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    return await published_phased_workflows(db, project_id=project_id, include_hidden=include_hidden)


def _unknown_workflow_key_resolution(workflow_key: str, available_keys: list[str]) -> dict[str, Any]:
    keys_text = ", ".join(available_keys) if available_keys else "none"
    return {
        "source": EXPLICIT_WORKFLOW_SELECTION_SOURCE,
        "status": EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY,
        "workflow_key": workflow_key,
        "unmatched_reason": (
            f"Unknown workflow_key '{workflow_key}'. It does not resolve to a published "
            f"workflow. Available workflow keys: {keys_text}."
        ),
        "available_workflow_keys": available_keys,
        "fallback_reason": None,
        "workflow_id": None,
        "workflow_class": None,
        "policy_id": None,
        "policy_version_id": None,
        "priority": None,
        "matched_group_id": None,
        "workflow_contract": None,
        "tool_policy": None,
        "safety_constraints": None,
    }


def project_inactive_resolution(project_id: str, workflow_key: str = "") -> dict[str, Any]:
    return {
        **_unknown_workflow_key_resolution(workflow_key, []),
        "source": "project_scope",
        "status": PROJECT_INACTIVE,
        "project_id": project_id,
        "unmatched_reason": (
            f"Project '{project_id}' is inactive (deleted or archived); no workflow is resolved for it."
        ),
    }


async def resolve_explicit_workflow_selection(
    db: AsyncSession,
    *,
    workflow_key: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    from ..run_admission.archived_workflows import archived_workflow_resolution, is_archived_workflow_key
    from ..run_admission.phased_catalog import phased_key, workflow_run_required_resolution

    normalized_key = str(workflow_key or "").strip()
    if await project_is_inactive(db, project_id):
        return project_inactive_resolution(str(project_id), normalized_key)
    available_keys = sorted(
        {str(item["key"]) for item in await list_published_workflow_definitions(db, project_id=project_id)}
    )
    base = _unknown_workflow_key_resolution(normalized_key, available_keys)
    if await phased_key(db, normalized_key, project_id=project_id):
        # A phased workflow is never a chat turn's contract: it starts as a workflow run (explicit state).
        return workflow_run_required_resolution(base, normalized_key)
    if await is_archived_workflow_key(db, normalized_key, project_id=project_id):
        return archived_workflow_resolution(base, normalized_key)
    return base


def explicit_mode_no_selection_resolution() -> dict[str, Any]:
    return {
        "source": "workflow_selection",
        "status": "unmatched",
        "unmatched_reason": "No workflow_key was provided and no workflow was proposed for this turn.",
        "fallback_reason": None,
        "workflow_id": None,
        "workflow_class": None,
        "policy_id": None,
        "policy_version_id": None,
        "priority": None,
        "matched_group_id": None,
        "workflow_contract": None,
        "tool_policy": None,
        "safety_constraints": None,
    }


async def resolve_workflow_selection_for_turn(
    db: AsyncSession,
    *,
    workflow_key: str = "",
    user_message: str,
    project_id: str | None = None,
    platform_workflow_service: str = "",
) -> dict[str, Any]:
    from .proposal import user_selected_no_workflow_resolution
    from .proposal_states import WORKFLOW_KEY_NONE

    clean_workflow_key = str(workflow_key or "").strip()
    if clean_workflow_key == WORKFLOW_KEY_NONE and not str(platform_workflow_service or "").strip():
        return user_selected_no_workflow_resolution()
    if await project_is_inactive(db, project_id):
        return project_inactive_resolution(str(project_id), clean_workflow_key)
    if str(platform_workflow_service or "").strip():
        from .platform_selection import platform_workflow_selection_resolution

        return platform_workflow_selection_resolution(platform_workflow_service)
    if clean_workflow_key:
        resolution = await resolve_explicit_workflow_selection(
            db, workflow_key=clean_workflow_key, project_id=project_id
        )
        if resolution.get("status") == "workflow_run_required":
            # A phased workflow is started, never refused: the turn waits for its one start confirmation.
            from ..workflow_runs.engine import published_phased_flow
            from .proposal import explicit_phased_selection_resolution

            phased = await published_phased_flow(db, clean_workflow_key, project_id)
            return explicit_phased_selection_resolution(clean_workflow_key, phased[0].name if phased else None)
        return resolution
    return explicit_mode_no_selection_resolution()


__all__ = [
    "EXPLICIT_WORKFLOW_SELECTION_SOURCE",
    "EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY",
    "explicit_mode_no_selection_resolution",
    "list_published_workflow_definitions",
    "project_inactive_resolution",
    "resolve_explicit_workflow_selection",
    "resolve_workflow_selection_for_turn",
]
