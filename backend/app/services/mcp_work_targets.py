"""Secondary configuration targets of a secure-work MCP call (``mcp_work_access``).

Workflow definitions (supplied, stored on a plan, or the default, including the one a coding start
transitions through) and repository profiles (supplied or stored on the selected change units, and the
code repository they wrap) must be owned by the Work Item's own workspace or be explicitly global
(``project_id`` is ``None``). A global profile may not wrap another workspace's code repository.
Incompatible targets answer exactly like missing ones and are refused before the service, so nothing is
read from or written for them.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CodeRepository, WorkChangePlan, WorkItem, WorkItemWorkflowDefinition, WorkRepositoryProfile
from .secure_work.coding.execution_scope import _selected_units as selected_change_units
from .secure_work.lifecycle_transitions import default_workflow_for_item
from .secure_work.workflow_access import WORKFLOW_NOT_FOUND


def _owned_compatibly(owner_project_id: str | None, item: WorkItem) -> bool:
    """Configuration usable for ``item``: explicitly global (``None``), or owned by the item's workspace.

    A blank string is not the global marker; it matches nothing.
    """
    return owner_project_id is None or owner_project_id == item.project_id


def workflow_compatible(workflow: WorkItemWorkflowDefinition | None, item: WorkItem) -> bool:
    return workflow is not None and _owned_compatibly(workflow.project_id, item)


async def compatible_workflow(db: AsyncSession, item: WorkItem, workflow_id: Any) -> WorkItemWorkflowDefinition:
    """A supplied workflow id that ``item`` may use; foreign answers like missing."""
    text = str(workflow_id or "").strip()
    workflow = await db.get(WorkItemWorkflowDefinition, text) if text else None
    if not workflow_compatible(workflow, item):
        raise HTTPException(status_code=404, detail=WORKFLOW_NOT_FOUND)
    return workflow


async def require_payload_workflow_compatible(db: AsyncSession, item: WorkItem, workflow_id: Any) -> None:
    """A workflow supplied for plan generation, if any; foreign answers like the service's missing."""
    if str(workflow_id or "").strip():
        await compatible_workflow(db, item, workflow_id)


async def require_plan_workflow_compatible(db: AsyncSession, plan: WorkChangePlan) -> None:
    """A decision previews the plan's stored workflow: it must fit the plan's own Work Item."""
    if not plan.workflow_id:
        return
    item = await db.get(WorkItem, plan.work_item_id)
    workflow = await db.get(WorkItemWorkflowDefinition, plan.workflow_id)
    if item is None or not workflow_compatible(workflow, item):
        raise HTTPException(status_code=409, detail="Change Plan workflow is not available for this Work Item")


async def transition_workflow_id(db: AsyncSession, item: WorkItem, workflow_id: Any) -> str:
    """The workflow a transition may use: a supplied compatible one, else a compatible default.

    ``default_workflow_for_item`` returns only the item's Workspace's or a global workflow; a foreign result
    (defense in depth) counts as none.
    """
    if str(workflow_id or "").strip():
        workflow = await compatible_workflow(db, item, workflow_id)
        return workflow.id
    workflow = await default_workflow_for_item(db, item)
    if not workflow_compatible(workflow, item):
        raise HTTPException(status_code=409, detail="No active workflow definition is configured")
    return workflow.id


async def require_compatible_repository_profiles(db: AsyncSession, item: WorkItem, units: Any) -> None:
    """Every ``repository_profile_id`` in ``units`` and the code repository it wraps fit ``item``."""
    if not isinstance(units, list):
        return
    for unit in units:
        if not isinstance(unit, dict):
            continue
        profile_id = str(unit.get("repository_profile_id") or "").strip()
        if profile_id and not await _profile_compatible(db, item, profile_id):
            raise HTTPException(status_code=404, detail="Repository profile not found")


async def _profile_compatible(db: AsyncSession, item: WorkItem, profile_id: str) -> bool:
    """The profile and the code repository it wraps (if any) both fit ``item``."""
    profile = await db.get(WorkRepositoryProfile, profile_id)
    if profile is None or not _owned_compatibly(profile.project_id, item):
        return False
    if not profile.code_repository_id:
        return True
    repository = await db.get(CodeRepository, profile.code_repository_id)
    return repository is not None and _owned_compatibly(repository.project_id, item)


async def require_coding_start_targets(db: AsyncSession, item: WorkItem, change_unit_ids: Any) -> None:
    """Indirect targets of a coding agent start, checked before the service runs.

    - The change units come from the service's own selector (``_selected_units``, reused as is), so
      the preflight sees exactly the units execution will prepare: the requested ids of this item,
      or all its active units. Each stored repository profile, and its code repository, must fit
      the item: persisted or REST data may point elsewhere.
    - The start ends with an automatic lifecycle transition through the default workflow. No
      default keeps the existing skip; a foreign default is refused before execution begins.
    """
    for unit in await selected_change_units(db, item, change_unit_ids):
        profile_id = str(unit.repository_profile_id or "").strip()
        if profile_id and not await _profile_compatible(db, item, profile_id):
            raise HTTPException(
                status_code=409, detail="Change unit repository profile is not available for this Work Item"
            )
    workflow = await default_workflow_for_item(db, item)
    if workflow is not None and not workflow_compatible(workflow, item):
        raise HTTPException(status_code=409, detail="Default lifecycle workflow is not available for this Work Item")


__all__ = [
    "compatible_workflow",
    "require_coding_start_targets",
    "require_compatible_repository_profiles",
    "require_payload_workflow_compatible",
    "require_plan_workflow_compatible",
    "transition_workflow_id",
    "workflow_compatible",
]
