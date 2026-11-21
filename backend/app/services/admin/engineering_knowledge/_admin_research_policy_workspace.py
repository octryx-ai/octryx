"""Workspace assignment of a published research policy version."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import Project, WorkspaceResearchPolicyAssignment
from ....services.research_policy import resolve_effective_research_policy
from ....time_utils import utc_now
from ._admin_research_policy_records import _get_version
from ._admin_research_policy_spec import _as_dict, _iso, _require_valid_spec, validate_research_policy_spec


async def get_workspace_research_policy(db: AsyncSession, *, workspace_id: str) -> dict[str, Any]:
    workspace = await db.get(Project, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    resolution = await resolve_effective_research_policy(db, workspace_id=workspace_id)
    assignment = (
        await db.execute(
            select(WorkspaceResearchPolicyAssignment)
            .options(selectinload(WorkspaceResearchPolicyAssignment.profile_version))
            .where(WorkspaceResearchPolicyAssignment.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    return {
        "workspace": {"id": workspace.id, "name": workspace.name},
        "assignment": {
            "id": assignment.id,
            "profile_version_id": assignment.profile_version_id,
            "assignment_status": assignment.assignment_status,
            "assigned_by_user_id": assignment.assigned_by_user_id,
            "assigned_at": _iso(assignment.assigned_at),
        }
        if assignment
        else None,
        "effective_policy": resolution,
        "diagnostics": validate_research_policy_spec(_as_dict(resolution.get("spec"))),
    }


async def update_workspace_research_policy(
    db: AsyncSession,
    *,
    workspace_id: str,
    admin_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if await db.get(Project, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    clear_assignment = bool(payload.get("clear_assignment"))
    assignment = (
        await db.execute(
            select(WorkspaceResearchPolicyAssignment).where(
                WorkspaceResearchPolicyAssignment.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if clear_assignment:
        if assignment is not None:
            assignment.assignment_status = "inactive"
            assignment.assigned_by_user_id = admin_id
            assignment.assigned_at = utc_now()
            await db.commit()
        return await get_workspace_research_policy(db, workspace_id=workspace_id)

    version_id = str(payload.get("profile_version_id") or "").strip()
    if not version_id:
        raise HTTPException(status_code=400, detail="profile_version_id is required")
    version = await _get_version(db, version_id)
    if version.status != "published":
        raise HTTPException(status_code=400, detail="Only published research policy versions can be assigned")
    _require_valid_spec(_as_dict(version.spec))
    if assignment is None:
        assignment = WorkspaceResearchPolicyAssignment(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            profile_version_id=version.id,
            assignment_status="active",
            assigned_by_user_id=admin_id,
            assigned_at=utc_now(),
        )
        db.add(assignment)
    else:
        assignment.profile_version_id = version.id
        assignment.assignment_status = "active"
        assignment.assigned_by_user_id = admin_id
        assignment.assigned_at = utc_now()
    await db.commit()
    return await get_workspace_research_policy(db, workspace_id=workspace_id)
