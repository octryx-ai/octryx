"""A transition is applied exactly as it was previewed.

The dry-run finishes its preview here: the target status is resolved (from the mapping, else read-only from
the issue's transitions), the effects are listed, and an ``effects_hash`` binds them together with the
workflow's ``updated_at``, the item and both states. The apply recomputes the same preview and must send
the hash it confirmed: a missing or different hash (the workflow or its mapping changed, or Jira now
offers another target) is 409 ``preview_stale`` before anything is written.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem, WorkItemWorkflowDefinition
from ...time_utils import ensure_utc
from .jira.jira_state_sync import check_offered_transition, jira_write_effects

CODE_PREVIEW_STALE = "preview_stale"
CODE_WORKFLOW_INACTIVE = "workflow_inactive"


def require_active(workflow: WorkItemWorkflowDefinition) -> None:
    """409 ``workflow_inactive``: a deactivated workflow neither previews nor applies (C-3)."""
    if not workflow.is_active:
        raise HTTPException(
            status_code=409,
            detail={"code": CODE_WORKFLOW_INACTIVE, "message": "The workflow is deactivated; activate it first"},
        )


def _effects_hash(workflow: WorkItemWorkflowDefinition, preview: dict[str, Any]) -> str:
    sync_preview = preview["jira_sync_preview"]
    canonical = {
        "workflow_id": workflow.id,
        "workflow_updated_at": sync_preview["workflow_updated_at"],
        "work_item_id": preview.get("work_item_id"),
        "from_state": preview.get("from_state"),
        "to_state": preview.get("to_state"),
        "will_mutate_jira": bool(sync_preview.get("will_mutate_jira")),
        "effects": sync_preview.get("effects") or [],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def finish_preview(
    db: AsyncSession, *, item: WorkItem, workflow: WorkItemWorkflowDefinition, preview: dict[str, Any]
) -> None:
    """Resolve the target status, list the effects and bind them with ``effects_hash`` (in place)."""
    sync_preview = preview["jira_sync_preview"]
    own_effects = _source_effects(item)
    if own_effects is None:
        await check_offered_transition(db, item=item, preview=preview)
        sync_preview["effects"] = jira_write_effects(item, preview) if sync_preview.get("will_mutate_jira") else []
    else:  # a registered source with its own write-back (Custom REST): never a Jira lookup
        sync_preview["effects"] = own_effects(item, preview)
    updated = workflow.updated_at or workflow.created_at
    sync_preview["workflow_updated_at"] = ensure_utc(updated).isoformat() if updated else None
    sync_preview["effects_hash"] = _effects_hash(workflow, preview)


def _source_effects(item: WorkItem):  # noqa: ANN202 - the source's ``write_effects`` or None
    from .intake.registry import source_for

    return getattr(source_for(item.source_type), "write_effects", None)


def require_previewed(preview: dict[str, Any], confirmed_hash: object) -> None:
    """409 ``preview_stale`` unless the apply sends the hash of exactly this preview."""
    if not isinstance(confirmed_hash, str) or confirmed_hash != preview["jira_sync_preview"].get("effects_hash"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": CODE_PREVIEW_STALE,
                "message": "The transition's effects changed or were not previewed; dry-run again and confirm them",
            },
        )


__all__ = [
    "CODE_PREVIEW_STALE",
    "CODE_WORKFLOW_INACTIVE",
    "finish_preview",
    "require_active",
    "require_previewed",
]
