"""DB lookup and validation helpers for design artifacts."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CodeRepository, ContextCheckpoint, Project, Session, Task, User


async def project_exists(db: AsyncSession, project_id: str) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def user_label_map(db: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(sorted(user_ids))))
    ).all()
    return {row[0]: str(row[1] or row[2] or "").strip() for row in rows}


async def project_repository_ids(db: AsyncSession, project_id: str) -> set[str]:
    rows = (await db.execute(select(CodeRepository.id).where(CodeRepository.project_id == project_id))).all()
    return {str(row[0]) for row in rows if row and row[0]}


async def project_task_options(db: AsyncSession, project_id: str) -> list[dict[str, str]]:
    rows = (
        await db.execute(
            select(Task.id, Task.name).where(Task.project_id == project_id).order_by(Task.created_at.desc())
        )
    ).all()
    return [{"id": str(row[0]), "name": str(row[1] or row[0])} for row in rows if row and row[0]]


async def validate_trace_target(
    db: AsyncSession,
    *,
    project_id: str,
    target_type: str,
    target_id: str | None,
) -> None:
    normalized_target_id = str(target_id or "").strip() or None
    if target_type == "task":
        if not normalized_target_id:
            raise HTTPException(status_code=400, detail="target_id is required for task trace links")
        row = await db.get(Task, normalized_target_id)
        if not row or str(row.project_id or "") != project_id:
            raise HTTPException(status_code=400, detail="Task target_id must belong to the same project")
        return
    if target_type == "session":
        if not normalized_target_id:
            raise HTTPException(status_code=400, detail="target_id is required for session trace links")
        row = await db.get(Session, normalized_target_id)
        if not row or str(row.project_id or "") != project_id:
            raise HTTPException(status_code=400, detail="Session target_id must belong to the same project")
        return
    if target_type == "code_repository":
        if not normalized_target_id:
            raise HTTPException(status_code=400, detail="target_id is required for code_repository trace links")
        row = await db.get(CodeRepository, normalized_target_id)
        if not row or str(row.project_id or "") != project_id:
            raise HTTPException(status_code=400, detail="Repository target_id must belong to the same project")
        return
    if target_type == "checkpoint":
        if not normalized_target_id:
            raise HTTPException(status_code=400, detail="target_id is required for checkpoint trace links")
        row = await db.get(ContextCheckpoint, normalized_target_id)
        if not row:
            # External CI/CD checkpoints may be referenced without local checkpoint rows.
            return
        session = await db.get(Session, str(row.session_id or ""))
        if not session or str(session.project_id or "") != project_id:
            raise HTTPException(status_code=400, detail="Checkpoint target_id must belong to the same project")
        return
