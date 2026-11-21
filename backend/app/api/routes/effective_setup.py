"""Effective setup (Agents & workflows → Overview): read-only, admin only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import AgentDefinition, Project, Role, Session, User, UserProject, UserRole
from ...services.auth import get_current_user
from ...services.effective_setup import (
    RUNTIME_CHAT,
    RUNTIME_OCTRYX_CLAUDE,
    RUNTIMES,
    chat_effective_setup,
    compare_prompt_refs,
    external_effective_setup,
    latest_turn_record,
    session_setup_inputs,
)
from ...services.notification_delivery import require_admin_user
from ...services.workflow_routing.explicit_selection import list_published_workflow_definitions

router = APIRouter(prefix="/api/v1/effective-setup", tags=["effective-setup"])


async def _user_roles(db: AsyncSession, user_id: str) -> list[str]:
    rows = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return [row[0] for row in rows.all()] or ["viewer"]


async def _setup(
    db: AsyncSession, *, runtime: str, user_id: str, project_id: str | None, agent_id: str, workflow_key: str
) -> dict[str, Any]:
    if runtime == RUNTIME_OCTRYX_CLAUDE:
        return await external_effective_setup(
            db, project_id=project_id, workflow_key=workflow_key, user_roles=await _user_roles(db, user_id)
        )
    return await chat_effective_setup(
        db, user_id=user_id, project_id=project_id, agent_id=agent_id, workflow_key=workflow_key
    )


def _runtime(value: str) -> str:
    runtime = (value or RUNTIME_CHAT).strip()
    if runtime not in RUNTIMES:
        raise HTTPException(status_code=422, detail=f"runtime must be one of: {', '.join(RUNTIMES)}")
    return runtime


@router.get("")
async def get_effective_setup(
    project_id: str | None = None,
    user_id: str | None = None,
    agent_id: str = "",
    workflow_key: str = "",
    runtime: str = RUNTIME_CHAT,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    target_user = (user_id or "").strip() or current_user.id
    if await db.get(User, target_user) is None:
        raise HTTPException(status_code=404, detail="User not found")
    setup = await _setup(
        db, runtime=_runtime(runtime), user_id=target_user, project_id=(project_id or "").strip() or None,
        agent_id=agent_id.strip(), workflow_key=workflow_key.strip(),
    )
    setup.pop("catalog_refs", None)
    return {"inputs": {"project_id": project_id, "user_id": target_user, "agent_id": agent_id,
                       "workflow_key": workflow_key}, **setup}


@router.get("/options")
async def get_effective_setup_options(
    project_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The pickers: active Workspaces, the Workspace's members, its agents and published workflows."""
    await require_admin_user(db, current_user)
    clean_project = (project_id or "").strip() or None
    projects = (await db.execute(
        select(Project.id, Project.name).where(Project.is_active.is_(True)).order_by(Project.name).limit(limit)
    )).all()
    user_query = select(User.id, User.username).order_by(User.username).limit(limit)
    if clean_project:
        user_query = user_query.join(UserProject, UserProject.user_id == User.id).where(
            UserProject.project_id == clean_project
        )
    agent_query = select(AgentDefinition.id, AgentDefinition.name, AgentDefinition.project_id).where(
        AgentDefinition.is_active.is_(True)
    )
    if clean_project:
        agent_query = agent_query.where(
            or_(AgentDefinition.project_id == clean_project, AgentDefinition.project_id.is_(None))
        )
    agents = (await db.execute(agent_query.order_by(AgentDefinition.name).limit(limit))).all()
    workflows = await list_published_workflow_definitions(db, project_id=clean_project)
    return {
        "projects": [{"id": row.id, "name": row.name} for row in projects],
        "users": [{"id": row.id, "username": row.username} for row in (await db.execute(user_query)).all()],
        "agents": [{"id": row.id, "name": row.name, "project_id": row.project_id} for row in agents],
        "workflows": [
            {"key": item.get("key"), "title": item.get("title"), "capability": item.get("capability")}
            for item in workflows
        ],
    }


@router.get("/sessions/{session_id}")
async def get_session_effective_setup(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What did this turn get? The session's latest turn next to the dry run of its inputs."""
    await require_admin_user(db, current_user)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    record = await latest_turn_record(db, session_id)
    inputs = session_setup_inputs(session)
    setup = await _setup(
        db, runtime=RUNTIME_CHAT, user_id=inputs["user_id"], project_id=inputs["project_id"] or None,
        agent_id=inputs["agent_id"], workflow_key=inputs["workflow_key"],
    )
    catalog_refs = setup.pop("catalog_refs", {})
    comparison = (
        compare_prompt_refs(setup["prompt_refs"], record["prompt_refs"], catalog_refs=catalog_refs) if record else None
    )
    return {"inputs": inputs, "turn": record, "comparison": comparison, **setup}


__all__ = ["router"]
