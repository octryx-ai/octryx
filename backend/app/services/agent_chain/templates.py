"""Agent-chain templates and runs: list, create, update, delete, read."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentChainRun, AgentChainTemplate, Project, User
from ...time_utils import utc_now
from .serialization import _normalize_steps, _serialize_run, _serialize_template


async def _get_project_or_404(db: AsyncSession, project_id: str | None) -> Project | None:
    if not project_id:
        return None
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_template_or_404(db: AsyncSession, template_id: str) -> AgentChainTemplate:
    row = await db.get(AgentChainTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent chain template not found")
    return row


async def _get_run_or_404(db: AsyncSession, run_id: str) -> AgentChainRun:
    row = await db.get(AgentChainRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent chain run not found")
    return row


async def list_agent_chain_templates(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(AgentChainTemplate).order_by(
        AgentChainTemplate.updated_at.desc(),
        AgentChainTemplate.created_at.desc(),
    )
    if project_id:
        stmt = stmt.where(AgentChainTemplate.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(AgentChainTemplate.is_active.is_(True))
    result = await db.execute(stmt)
    return [_serialize_template(row) for row in result.scalars().all()]


async def create_agent_chain_template(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _get_project_or_404(db, payload.get("project_id"))
    row = AgentChainTemplate(
        name=str(payload.get("name") or "").strip(),
        description=str(payload.get("description") or "").strip() or None,
        project_id=payload.get("project_id"),
        created_by=current_user.id,
        is_active=bool(payload.get("is_active", True)),
        steps_json=_normalize_steps(payload.get("steps") or []),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_template(row)


async def update_agent_chain_template(
    db: AsyncSession,
    *,
    template_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = await _get_template_or_404(db, template_id)
    if "project_id" in payload:
        await _get_project_or_404(db, payload.get("project_id"))
        row.project_id = payload.get("project_id")
    if "name" in payload and payload.get("name") is not None:
        row.name = str(payload.get("name") or "").strip()
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    if "is_active" in payload and payload.get("is_active") is not None:
        row.is_active = bool(payload.get("is_active"))
    if "steps" in payload and payload.get("steps") is not None:
        row.steps_json = _normalize_steps(payload.get("steps") or [])
    row.updated_at = utc_now()
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_template(row)


async def delete_agent_chain_template(db: AsyncSession, *, template_id: str) -> dict[str, Any]:
    row = await _get_template_or_404(db, template_id)
    await db.execute(delete(AgentChainRun).where(AgentChainRun.template_id == row.id))
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": template_id}


async def list_agent_chain_runs(
    db: AsyncSession,
    *,
    template_id: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = select(AgentChainRun).order_by(AgentChainRun.started_at.desc()).limit(max(1, min(int(limit or 20), 100)))
    if template_id:
        stmt = stmt.where(AgentChainRun.template_id == template_id)
    if project_id:
        stmt = stmt.where(AgentChainRun.project_id == project_id)
    result = await db.execute(stmt)
    return [_serialize_run(row) for row in result.scalars().all()]


async def get_agent_chain_run(db: AsyncSession, *, run_id: str) -> dict[str, Any]:
    return _serialize_run(await _get_run_or_404(db, run_id))
