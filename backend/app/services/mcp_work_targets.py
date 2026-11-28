"""Secondary configuration targets of a secure-work MCP call (``mcp_work_access``). Workflows and repository profiles
must belong to the Work Item's own workspace or be explicitly global."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CodeRepository, WorkChangePlan, WorkItem, WorkItemWorkflowDefinition, WorkRepositoryProfile
from .secure_work.coding.execution_scope import _selected_units as selected_change_units
from .secure_work.lifecycle_transitions import default_workflow_for_item
from .secure_work.workflow_access import WORKFLOW_NOT_FOUND


def _owned_compatibly(owner_project_id: str | None, item: WorkItem) -> bool:
    # A blank string is not the global marker; it matches nothing.
    return owner_project_id is None or owner_project_id == item.project_id


def workflow_compatible(workflow: WorkItemWorkflowDefinition | None, item: WorkItem) -> bool:
    return workflow is not None and _owned_compatibly(workflow.project_id, item)


async def compatible_workflow(db: AsyncSession, item: WorkItem, workflow_id: Any) -> WorkItemWorkflowDefinition:
    # A foreign workflow answers like a missing one.
    text = str(workflow_id or "").strip()
    workflow = await db.get(WorkItemWorkflowDefinition, text) if text else None
    if not workflow_compatible(workflow, item):
        raise HTTPException(status_code=404, detail=WORKFLOW_NOT_FOUND)
    return workflow


async def require_payload_workflow_compatible(db: AsyncSession, item: WorkItem, workflow_id: Any) -> None:
    # A foreign workflow answers like the service's missing one.
    if str(workflow_id or "").strip():
        await compatible_workflow(db, item, workflow_id)


async def require_plan_workflow_compatible(db: AsyncSession, plan: WorkChangePlan) -> None:
    if not plan.workflow_id:
        return
    item = await db.get(WorkItem, plan.work_item_id)
    workflow = await db.get(WorkItemWorkflowDefinition, plan.workflow_id)
    if item is None or not workflow_compatible(workflow, item):
        raise HTTPException(status_code=409, detail="Change Plan workflow is not available for this Work Item")


async def transition_workflow_id(db: AsyncSession, item: WorkItem, workflow_id: Any) -> str:
    # A foreign default counts as none (defense in depth).
    if str(workflow_id or "").strip():
        workflow = await compatible_workflow(db, item, workflow_id)
        return workflow.id
    workflow = await default_workflow_for_item(db, item)
    if not workflow_compatible(workflow, item):
        raise HTTPException(status_code=409, detail="No active workflow definition is configured")
    return workflow.id


async def require_compatible_repository_profiles(db: AsyncSession, item: WorkItem, units: Any) -> None:
    if not isinstance(units, list):
        return
    for unit in units:
        if not isinstance(unit, dict):
            continue
        profile_id = str(unit.get("repository_profile_id") or "").strip()
        if profile_id and not await _profile_compatible(db, item, profile_id):
            raise HTTPException(status_code=404, detail="Repository profile not found")


async def _profile_compatible(db: AsyncSession, item: WorkItem, profile_id: str) -> bool:
    profile = await db.get(WorkRepositoryProfile, profile_id)
    if profile is None or not _owned_compatibly(profile.project_id, item):
        return False
    if not profile.code_repository_id:
        return True
    repository = await db.get(CodeRepository, profile.code_repository_id)
    return repository is not None and _owned_compatibly(repository.project_id, item)


async def require_coding_start_targets(db: AsyncSession, item: WorkItem, change_unit_ids: Any) -> None:
    # Stored profiles and repositories must fit the item: persisted or REST data may point elsewhere. A foreign default
    # workflow is refused before execution.
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
