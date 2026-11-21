"""Workspace scope of Secure Work workflows.

``require_work_operator`` is the platform-role gate; on top of it, every workflow operation is bound to
the Workspace the workflow belongs to, under the same membership policy as Work Items
(``access.work_scope_project_ids``): a platform admin is cross-workspace, everyone else needs access to
the workflow's project.

- Creating, changing, deactivating and activating a workflow needs access to its project; a global
  workflow (no project) can be created and changed by a platform admin only.
- Listing shows the global workflows and those of the caller's Workspaces; asking for a project outside
  them is a 403.
- A workflow of a Workspace outside the caller's scope answers like a missing one (404), before anything else is
  looked up for the request.
- A transition needs access to the workflow and to the item's Workspace (403 first), and the workflow must
  be the item's Workspace's own or a global one (409 ``workflow_project_mismatch`` otherwise). The scope
  check (``require_workflow_scope``) also binds internal flow points that skip the user ACL.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkItem, WorkItemWorkflowDefinition
from .access import require_work_item_scope, work_scope_project_ids

CODE_PROJECT_MISMATCH = "workflow_project_mismatch"
WORKFLOW_NOT_FOUND = "Workflow definition not found"


async def require_project_access(db: AsyncSession, user: User, project_id: str | None) -> None:
    """403 unless ``user`` may manage workflows of ``project_id`` (global: platform admin only)."""
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
    """``user`` may use (``change=False``) or change the workflow: a workflow of a Workspace outside the caller's
    scope answers like a missing one (404); changing a global one is 403 for anyone but a platform admin."""
    if workflow.project_id is None and not change:
        return
    scope = await work_scope_project_ids(db, user)
    if scope is not None and workflow.project_id is not None and workflow.project_id not in scope:
        raise HTTPException(status_code=404, detail=WORKFLOW_NOT_FOUND)
    await require_project_access(db, user, workflow.project_id)


async def visible_project_ids(db: AsyncSession, user: User, project_id: str | None) -> set[str] | None:
    """The Workspaces a listing may show (``None``: all); 403 for a requested project out of scope."""
    scope = await work_scope_project_ids(db, user)
    if scope is not None and project_id and project_id not in scope:
        raise HTTPException(status_code=403, detail="The requested Workspace is outside your access")
    return scope


def require_workflow_scope(workflow: WorkItemWorkflowDefinition, item: WorkItem) -> None:
    """409 ``workflow_project_mismatch`` unless ``workflow`` is the item's Workspace's own or a global one.

    A global workflow (no project) passes for every item, including one without a Workspace. This is the
    configuration scope, not a user ACL: ``check_access=False`` may skip the ACL, never this check.
    """
    if workflow.project_id is not None and workflow.project_id != item.project_id:
        raise HTTPException(
            status_code=409,
            detail={"code": CODE_PROJECT_MISMATCH, "message": "The workflow belongs to another Workspace"},
        )


async def require_transition_access(
    db: AsyncSession, user: User, workflow: WorkItemWorkflowDefinition, item: WorkItem
) -> None:
    """The user ACL first (403 for the item's or the workflow's Workspace), then the scope (409)."""
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
