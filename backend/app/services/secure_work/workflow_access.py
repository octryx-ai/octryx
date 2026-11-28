"""Workspace scope of Secure Work workflows."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkItem, WorkItemWorkflowDefinition
from ..project.private_workspace import refuse_foreign_private
from .access import require_work_item_scope, work_scope_project_ids

CODE_PROJECT_MISMATCH = "workflow_project_mismatch"
WORKFLOW_NOT_FOUND = "Workflow definition not found"


async def require_project_access(db: AsyncSession, user: User, project_id: str | None) -> None:
    scope = await work_scope_project_ids(db, user)
    if scope is None:
        return
    if project_id is None:
        raise HTTPException(status_code=403, detail="Only a platform admin can manage a global workflow")
    if project_id not in scope:
        raise HTTPException(status_code=403, detail="The workflow's Workspace is outside your access")


async def require_workflow_access(
    db: AsyncSession, user: User, workflow: WorkItemWorkflowDefinition, *, change: bool
) -> None:
    if workflow.project_id is None and not change:
        return
    scope = await work_scope_project_ids(db, user)
    if (scope is not None and workflow.project_id is not None and workflow.project_id not in scope) or (
            scope is None and await refuse_foreign_private(db, workflow.project_id, user.id)):
        # Another Workspace's workflow answers like a missing one
        raise HTTPException(status_code=404, detail=WORKFLOW_NOT_FOUND)
    await require_project_access(db, user, workflow.project_id)


async def visible_project_ids(db: AsyncSession, user: User, project_id: str | None) -> set[str] | None:
    scope = await work_scope_project_ids(db, user)
    if scope is not None and project_id and project_id not in scope:
        raise HTTPException(status_code=403, detail="The requested Workspace is outside your access")
    return scope


def require_workflow_scope(workflow: WorkItemWorkflowDefinition, item: WorkItem) -> None:
    # The configuration scope, not a user ACL: a flow point that skips the ACL never skips this
    if workflow.project_id is not None and workflow.project_id != item.project_id:
        raise HTTPException(
            status_code=409,
            detail={"code": CODE_PROJECT_MISMATCH, "message": "The workflow belongs to another Workspace"},
        )


async def require_transition_access(
    db: AsyncSession, user: User, workflow: WorkItemWorkflowDefinition, item: WorkItem
) -> None:
    await require_work_item_scope(db, user, item)
    await require_workflow_access(db, user, workflow, change=False)
    require_workflow_scope(workflow, item)


__all__ = [
    "CODE_PROJECT_MISMATCH",
    "WORKFLOW_NOT_FOUND",
    "require_project_access",
    "require_transition_access",
    "require_workflow_access",
    "require_workflow_scope",
    "visible_project_ids",
]
