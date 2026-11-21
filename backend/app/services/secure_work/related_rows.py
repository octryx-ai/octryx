"""The one scoped loader of the related rows a Secure Work handler consumes.

A handler that uses a row it did not address itself — named by a request field (top level or nested, such as a
change unit's ``repository_profile_id``) or stored on another row (a plan's ``workflow_id``, a change unit's
profile) — loads it here, with the acting user, before it reads or copies anything from it:

- a row that does not exist and a row of a Workspace outside the caller's (``access.work_scope_project_ids``; for a
  row bound to a Work Item: its item's) are the same 404 with the family's own wording; a row bound to a Work Item
  without a Workspace is admin-only and answers the same 404 to everyone else; a global row (no Workspace) is
  visible to every caller;
- only then, for everyone (platform admins included), the row's fit for the Workspace it is used for
  (``for_workspace``): a global row fits every Workspace, a row of another Workspace is the family's mismatch answer
  (data integrity, not access). ``for_workspace=None`` (an item without a Workspace) admits global rows only.

The addressed records of a request (path ids, ``work_item_id``, ``change_unit_id``, ``project_id``) are the route
dependency's (``api/routes/_secure_work_scope.py``); the MCP surface keeps its narrower grant-bound prechecks
(``mcp_work_targets``).
"""

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
from .access import work_scope_project_ids
from .workflow_access import CODE_PROJECT_MISMATCH, WORKFLOW_NOT_FOUND

OTHER_WORKSPACE = "The referenced configuration belongs to another Workspace"
# ``for_workspace`` default: the row is not used for one Workspace (no fit check).
ANY_WORKSPACE: Any = object()
_ADMIN_ONLY = object()


@dataclass(frozen=True)
class RelatedFamily:
    """A kind of related row: its model, the answer for a row that names nothing, and the answer for an authorized
    row of another Workspace than the one it is used for."""

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
    """A config row's ``project_id`` (``None``: global); for a row bound to a Work Item its item's, ``_ADMIN_ONLY``
    when the item has none."""
    if hasattr(row, "project_id"):
        return row.project_id
    item = await db.get(WorkItem, row.work_item_id)
    return item.project_id if item is not None and item.project_id else _ADMIN_ONLY


async def load_related(
    db: AsyncSession, viewer: User, family: RelatedFamily, row_id: str, *, for_workspace: Any = ANY_WORKSPACE
) -> Any:
    """The ``family`` row ``row_id`` when ``viewer`` may use it (see the module doc), else the family's 404; then the
    family's mismatch answer unless it fits ``for_workspace``."""
    row = await db.get(family.model, row_id) if row_id else None
    owner = await _workspace_of(db, row) if row is not None else _ADMIN_ONLY
    scope = await work_scope_project_ids(db, viewer)
    if row is None or (scope is not None and owner is not None and (owner is _ADMIN_ONLY or owner not in scope)):
        raise HTTPException(status_code=404, detail=family.missing)
    if for_workspace is not ANY_WORKSPACE and owner not in (None, _ADMIN_ONLY) and owner != for_workspace:
        raise HTTPException(status_code=family.mismatch_status, detail=family.mismatch_detail)
    return row


async def load_usable_related(
    db: AsyncSession, viewer: User | None, family: RelatedFamily, row_id: str | None, *, for_workspace: Any
) -> Any | None:
    """A stored reference a worker or a recommendation consumes (no request to answer): the row ``load_related``
    admits for ``viewer`` and ``for_workspace``, else ``None`` (missing, invisible or of another Workspace: never
    used)."""
    if viewer is None or not row_id:
        return None
    try:
        return await load_related(db, viewer, family, row_id, for_workspace=for_workspace)
    except HTTPException:
        return None


async def load_optional_related(
    db: AsyncSession, viewer: User, family: RelatedFamily, row_id: str | None, *, for_workspace: Any = ANY_WORKSPACE
) -> Any | None:
    """``load_related`` for an optional reference: ``None`` when no id is given."""
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
