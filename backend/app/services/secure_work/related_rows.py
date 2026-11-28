"""The one scoped loader of the related rows a Secure Work handler consumes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    User,
    WorkChangePlan,
    WorkCicdPipelineTrace,
    WorkCicdProviderConfig,
    WorkCodingPipelineConfig,
    WorkItem,
    WorkItemWorkflowDefinition,
    WorkRepositoryProfile,
)
from ..project.private_workspace import refuse_foreign_private
from .access import work_scope_project_ids
from .workflow_access import CODE_PROJECT_MISMATCH, WORKFLOW_NOT_FOUND

OTHER_WORKSPACE = "The referenced configuration belongs to another Workspace"
# ``for_workspace`` default: the row is not used for one Workspace (no fit check).
ANY_WORKSPACE: Any = object()
_ADMIN_ONLY = object()


@dataclass(frozen=True)
class RelatedFamily:
    model: type
    missing: str
    mismatch_status: int = 403
    mismatch_detail: Any = OTHER_WORKSPACE


REPOSITORY_PROFILE = RelatedFamily(WorkRepositoryProfile, "Repository profile not found")
WORKFLOW = RelatedFamily(
    WorkItemWorkflowDefinition,
    WORKFLOW_NOT_FOUND,
    409,
    {"code": CODE_PROJECT_MISMATCH, "message": "The workflow belongs to another Workspace"},
)
PIPELINE_CONFIG = RelatedFamily(WorkCodingPipelineConfig, "Coding pipeline config not found")
CICD_PROVIDER = RelatedFamily(WorkCicdProviderConfig, "CI/CD provider not found")
PIPELINE_TRACE = RelatedFamily(WorkCicdPipelineTrace, "CI/CD pipeline trace not found")
CHANGE_PLAN = RelatedFamily(WorkChangePlan, "Change Plan not found")


async def _workspace_of(db: AsyncSession, row: Any) -> Any:
    # A row bound to a Work Item without a Workspace is admin only.
    if hasattr(row, "project_id"):
        return row.project_id
    item = await db.get(WorkItem, row.work_item_id)
    return item.project_id if item is not None and item.project_id else _ADMIN_ONLY


async def load_related(
    db: AsyncSession, viewer: User, family: RelatedFamily, row_id: str, *, for_workspace: Any = ANY_WORKSPACE
) -> Any:
    row = await db.get(family.model, row_id) if row_id else None
    owner = await _workspace_of(db, row) if row is not None else _ADMIN_ONLY
    scope = await work_scope_project_ids(db, viewer)
    if row is None or (scope is not None and owner is not None and (owner is _ADMIN_ONLY or owner not in scope)) or (
            scope is None and isinstance(owner, str) and await refuse_foreign_private(db, owner, viewer.id)):
        # Missing, out of scope and admin-only rows answer alike
        raise HTTPException(status_code=404, detail=family.missing)
    if for_workspace is not ANY_WORKSPACE and owner not in (None, _ADMIN_ONLY) and owner != for_workspace:
        # Data integrity, not access: also for a platform admin
        raise HTTPException(status_code=family.mismatch_status, detail=family.mismatch_detail)
    return row


async def load_usable_related(
    db: AsyncSession, viewer: User | None, family: RelatedFamily, row_id: str | None, *, for_workspace: Any
) -> Any | None:
    if viewer is None or not row_id:
        return None
    try:
        return await load_related(db, viewer, family, row_id, for_workspace=for_workspace)
    except HTTPException:
        return None


async def load_optional_related(
    db: AsyncSession, viewer: User, family: RelatedFamily, row_id: str | None, *, for_workspace: Any = ANY_WORKSPACE
) -> Any | None:
    if not row_id:
        return None
    return await load_related(db, viewer, family, row_id, for_workspace=for_workspace)


__all__ = [
    "ANY_WORKSPACE",
    "CHANGE_PLAN",
    "CICD_PROVIDER",
    "OTHER_WORKSPACE",
    "PIPELINE_CONFIG",
    "PIPELINE_TRACE",
    "REPOSITORY_PROFILE",
    "WORKFLOW",
    "RelatedFamily",
    "load_optional_related",
    "load_related",
    "load_usable_related",
]
