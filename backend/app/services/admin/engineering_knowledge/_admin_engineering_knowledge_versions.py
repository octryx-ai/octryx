"""Pack-version and assignment helpers for Engineering Knowledge admin services."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import (
    CodeRepository,
    EngineeringKnowledgePackAssignment,
    EngineeringKnowledgePackBuildRun,
    EngineeringKnowledgePackVersion,
    Project,
)
from ....time_utils import utc_now
from ...engineering_knowledge import (
    deactivate_engineering_knowledge_retrieval_index,
    rebuild_engineering_knowledge_retrieval_index,
    search_engineering_knowledge_retrieval_index,
)
from ._admin_engineering_knowledge_common import (
    _VALID_ASSIGNMENT_STATUSES,
    _VALID_SCOPE_TYPES,
    _optional_id,
)
from ._admin_engineering_knowledge_serialization import as_dict, serialize_assignment, serialize_version


async def search_engineering_knowledge_pack_version_retrieval(
    db: AsyncSession,
    *,
    version_id: str,
    query: str = "",
    record_kind: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    version = await _get_pack_version(db, version_id=version_id)
    return await search_engineering_knowledge_retrieval_index(
        db,
        query=query,
        pack_version_id=version.id,
        record_kind=record_kind,
        limit=limit,
    )


async def _get_pack_version(db: AsyncSession, *, version_id: str) -> EngineeringKnowledgePackVersion:
    version = (
        await db.execute(
            select(EngineeringKnowledgePackVersion)
            .options(
                selectinload(EngineeringKnowledgePackVersion.pack),
                selectinload(EngineeringKnowledgePackVersion.sources),
                selectinload(EngineeringKnowledgePackVersion.items),
                selectinload(EngineeringKnowledgePackVersion.assignments),
            )
            .where(EngineeringKnowledgePackVersion.id == version_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge Pack version not found")
    return version


async def publish_engineering_knowledge_pack_version(
    db: AsyncSession,
    *,
    version_id: str,
    admin_id: str,
) -> dict[str, Any]:
    version = await _get_pack_version(db, version_id=version_id)
    if version.status == "published":
        return serialize_version(version, include_details=True)
    if version.status not in {"draft", "pending_review"}:
        raise HTTPException(
            status_code=400,
            detail="Only draft or pending-review Engineering Knowledge Pack versions can be published",
        )
    if version.quality_status != "passed" or as_dict(version.quality_report).get("passed") is False:
        raise HTTPException(status_code=400, detail="Only quality-passed pack versions can be published")
    version.status = "published"
    version.published_by_user_id = admin_id
    version.published_at = utc_now()
    index_result = await rebuild_engineering_knowledge_retrieval_index(db, pack_version_id=version.id)
    report = as_dict(version.quality_report)
    report["retrieval_index"] = index_result
    version.quality_report = report
    await _mark_build_runs_reviewed(
        db,
        version_id=version.id,
        status="published",
        publish_decision="published",
        approval_status="approved",
    )
    # The published pack is served through its own retrieval index.
    await db.commit()
    return serialize_version(await _get_pack_version(db, version_id=version.id), include_details=True)


async def reject_engineering_knowledge_pack_version(
    db: AsyncSession,
    *,
    version_id: str,
    admin_id: str,
    reason: str = "",
) -> dict[str, Any]:
    version = await _get_pack_version(db, version_id=version_id)
    if version.status == "published":
        raise HTTPException(status_code=400, detail="Published Engineering Knowledge Pack versions cannot be rejected")
    version.status = "rejected"
    await deactivate_engineering_knowledge_retrieval_index(db, pack_version_id=version.id)
    report = as_dict(version.quality_report)
    report["admin_review"] = {"status": "rejected", "reason": reason, "reviewed_by_user_id": admin_id}
    version.quality_report = report
    await _mark_build_runs_reviewed(
        db,
        version_id=version.id,
        status="rejected",
        publish_decision="rejected",
        approval_status="rejected",
    )
    await db.commit()
    return serialize_version(await _get_pack_version(db, version_id=version.id), include_details=True)


async def _mark_build_runs_reviewed(
    db: AsyncSession,
    *,
    version_id: str,
    status: str,
    publish_decision: str,
    approval_status: str,
) -> None:
    runs = (
        await db.execute(
            select(EngineeringKnowledgePackBuildRun).where(EngineeringKnowledgePackBuildRun.pack_version_id == version_id)
        )
    ).scalars()
    for run in runs:
        run.status = status
        run.publish_decision = publish_decision
        run.approval_status = approval_status
        run.completed_at = run.completed_at or utc_now()
    await db.flush()


async def assign_engineering_knowledge_pack_version(
    db: AsyncSession,
    *,
    version_id: str,
    admin_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    version = await _get_pack_version(db, version_id=version_id)
    if version.status != "published":
        raise HTTPException(status_code=400, detail="Only published Engineering Knowledge Pack versions can be assigned")
    scope_type = str(payload.get("scope_type") or "global").strip()
    if scope_type not in _VALID_SCOPE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid Engineering Knowledge Pack assignment scope")
    assignment_status = str(payload.get("assignment_status") or "active").strip()
    if assignment_status not in _VALID_ASSIGNMENT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid Engineering Knowledge Pack assignment status")
    scope_id = _optional_id(payload.get("scope_id"))
    workspace_id = _optional_id(payload.get("workspace_id"))
    repository_id = _optional_id(payload.get("repository_id"))
    if workspace_id and await db.get(Project, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if repository_id and await db.get(CodeRepository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if scope_type in {"workspace", "project"} and not (workspace_id or scope_id):
        raise HTTPException(status_code=400, detail="workspace_id or scope_id is required for workspace scope")
    if scope_type == "repository" and not (repository_id or scope_id):
        raise HTTPException(status_code=400, detail="repository_id or scope_id is required for repository scope")

    stack_key = str(payload.get("stack_key") or version.pack.stack_key or "").strip()
    if not stack_key:
        raise HTTPException(status_code=400, detail="stack_key is required")
    assignment = await _find_assignment(
        db,
        version_id=version.id,
        scope_type=scope_type,
        scope_id=scope_id,
        workspace_id=workspace_id,
        repository_id=repository_id,
        stack_key=stack_key,
    )
    if assignment is None:
        assignment = EngineeringKnowledgePackAssignment(id=str(uuid.uuid4()), pack_version_id=version.id)
        db.add(assignment)
    assignment.scope_type = scope_type
    assignment.scope_id = scope_id
    assignment.workspace_id = workspace_id
    assignment.repository_id = repository_id
    assignment.stack_key = stack_key
    assignment.assignment_status = assignment_status
    assignment.priority = int(payload.get("priority") or 100)
    assignment.assignment_policy = as_dict(payload.get("assignment_policy"))
    assignment.assigned_by_user_id = admin_id
    assignment.assigned_at = utc_now()
    if assignment_status == "active":
        await _deactivate_overlapping_assignments(db, keep_assignment=assignment)
    await db.commit()
    return serialize_assignment(assignment)


async def _find_assignment(
    db: AsyncSession,
    *,
    version_id: str,
    scope_type: str,
    scope_id: str | None,
    workspace_id: str | None,
    repository_id: str | None,
    stack_key: str,
) -> EngineeringKnowledgePackAssignment | None:
    stmt = select(EngineeringKnowledgePackAssignment).where(
        EngineeringKnowledgePackAssignment.pack_version_id == version_id,
        EngineeringKnowledgePackAssignment.scope_type == scope_type,
        EngineeringKnowledgePackAssignment.stack_key == stack_key,
    )
    stmt = stmt.where(
        EngineeringKnowledgePackAssignment.scope_id == scope_id
        if scope_id
        else EngineeringKnowledgePackAssignment.scope_id.is_(None)
    )
    stmt = stmt.where(
        EngineeringKnowledgePackAssignment.workspace_id == workspace_id
        if workspace_id
        else EngineeringKnowledgePackAssignment.workspace_id.is_(None)
    )
    stmt = stmt.where(
        EngineeringKnowledgePackAssignment.repository_id == repository_id
        if repository_id
        else EngineeringKnowledgePackAssignment.repository_id.is_(None)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _deactivate_overlapping_assignments(
    db: AsyncSession,
    *,
    keep_assignment: EngineeringKnowledgePackAssignment,
) -> None:
    await db.flush()
    stmt = select(EngineeringKnowledgePackAssignment).where(
        EngineeringKnowledgePackAssignment.id != keep_assignment.id,
        EngineeringKnowledgePackAssignment.scope_type == keep_assignment.scope_type,
        EngineeringKnowledgePackAssignment.stack_key == keep_assignment.stack_key,
        EngineeringKnowledgePackAssignment.assignment_status == "active",
    )
    stmt = stmt.where(
        EngineeringKnowledgePackAssignment.scope_id == keep_assignment.scope_id
        if keep_assignment.scope_id
        else EngineeringKnowledgePackAssignment.scope_id.is_(None)
    )
    stmt = stmt.where(
        EngineeringKnowledgePackAssignment.workspace_id == keep_assignment.workspace_id
        if keep_assignment.workspace_id
        else EngineeringKnowledgePackAssignment.workspace_id.is_(None)
    )
    stmt = stmt.where(
        EngineeringKnowledgePackAssignment.repository_id == keep_assignment.repository_id
        if keep_assignment.repository_id
        else EngineeringKnowledgePackAssignment.repository_id.is_(None)
    )
    overlaps = (await db.execute(stmt)).scalars().all()
    for overlap in overlaps:
        overlap.assignment_status = "inactive"
    await db.flush()
