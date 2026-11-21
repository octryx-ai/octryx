"""Explicit workflow selection: a chat turn's ``workflow_key`` -> an explicit state.

Rules:

- The workflow catalog is exactly the published phased workflows (``run_admission.phased_catalog``).
- A phased workflow never runs inside a chat turn: its key resolves to ``workflow_run_required``, and the turn
  is held for its one start confirmation (``proposal.explicit_phased_selection_resolution``).
- An archived or switched-off phased workflow is the typed denial ``workflow_archived``.
- Any other key is the explicit error state ``unknown_key`` that the execution profile maps to
  ``needs_clarification``; nothing is guessed.
- A turn without a ``workflow_key`` gets the Workspace's workflow proposal (``proposal.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..project_activity import PROJECT_INACTIVE, project_is_inactive
from ..run_admission.phased_catalog import published_phased_workflows

if TYPE_CHECKING:
    from .proposal_prefetch import PrecomputedWorkflowProposal

EXPLICIT_WORKFLOW_SELECTION_SOURCE = "explicit_workflow_key"
EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY = "unknown_key"


async def list_published_workflow_definitions(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    """The workflow catalog: the published phased workflows.

    ``include_hidden``: also test fixtures and workflows a pull request starts (the admin view only, never a
    catalog a person or a model chooses from).
    """
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
    """Explicit refusal: the turn's project is deleted or archived, so nothing scoped to it is used."""
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
    """Deterministically resolve ``workflow_key``: ``workflow_run_required``, ``workflow_archived`` or
    ``unknown_key``; the same key always produces the same resolution."""
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
    """The unmatched resolution of a turn that runs without a workflow (plain chat)."""
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
    precomputed_proposal: PrecomputedWorkflowProposal | None = None,
    platform_workflow_service: str = "",
) -> dict[str, Any]:
    """Single turn-level selection entry point.

    Precedence: an inactive Workspace (``project_inactive``) > a platform service's own
    workflow (``platform_selection``, closed set; no proposal call) > explicit
    ``workflow_key`` (deterministic, never a proposal call) > explicit "no workflow"
    (``WORKFLOW_KEY_NONE``) > the Workspace's workflow proposal (``proposal.py``).

    ``precomputed_proposal`` is the proposal the web chat path resolved before its
    process-global preparation lock (``proposal_prefetch.py``). When it is given, no
    proposal model call is made here: a key mismatch is ``proposal_scope_changed``.
    """
    from .proposal import resolve_workflow_proposal_for_turn, user_selected_no_workflow_resolution
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
    if precomputed_proposal is not None:
        return precomputed_proposal.resolution_for_turn(user_message=user_message, project_id=project_id)
    return await resolve_workflow_proposal_for_turn(db, user_message=user_message, project_id=project_id)


__all__ = [
    "EXPLICIT_WORKFLOW_SELECTION_SOURCE",
    "EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY",
    "explicit_mode_no_selection_resolution",
    "list_published_workflow_definitions",
    "project_inactive_resolution",
    "resolve_explicit_workflow_selection",
    "resolve_workflow_selection_for_turn",
]
