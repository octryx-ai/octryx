from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.operations.agent_chain import (
    AgentChainRunCreateRequest,
    AgentChainTemplateCreateRequest,
    AgentChainTemplateUpdateRequest,
)
from ...services.access_control import require_project_access
from ...services.agent_chain import (
    create_agent_chain_template,
    delete_agent_chain_template,
    execute_agent_chain,
    get_agent_chain_run,
    list_agent_chain_runs,
    list_agent_chain_templates,
    update_agent_chain_template,
)
from ...services.agent_chain.access import require_template_access, require_template_scope
from ...services.auth import get_current_user

router = APIRouter(prefix="/api/v1/agent-chains", tags=["agent-chains"])


@router.get("/templates")
async def api_list_agent_chain_templates(
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, project_id)
    return await list_agent_chain_templates(
        db,
        project_id=project_id,
        include_inactive=include_inactive,
    )


@router.post("/templates")
async def api_create_agent_chain_template(
    body: AgentChainTemplateCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, body.project_id)
    await require_template_scope(db, current_user, body.project_id)
    return await create_agent_chain_template(
        db,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.put("/templates/{template_id}")
async def api_update_agent_chain_template(
    template_id: str,
    body: AgentChainTemplateUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, body.project_id)
    template = await require_template_access(db, current_user, template_id)
    payload = body.model_dump(exclude_unset=True)
    if "project_id" in payload and payload["project_id"] != template.project_id:
        await require_template_scope(db, current_user, payload["project_id"])  # moving needs the target too
    return await update_agent_chain_template(db, template_id=template_id, payload=payload)


@router.delete("/templates/{template_id}")
async def api_delete_agent_chain_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_template_access(db, current_user, template_id)
    return await delete_agent_chain_template(db, template_id=template_id)


@router.post("/templates/{template_id}/run")
async def api_run_agent_chain_template(
    template_id: str,
    body: AgentChainRunCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_template_access(db, current_user, template_id)
    return await execute_agent_chain(
        db,
        template_id=template_id,
        current_user=current_user,
        input_payload=body.input_payload,
        parent_session_id=body.parent_session_id,
        session_factory=request.app.state.async_session_factory,
    )


@router.get("/runs")
async def api_list_agent_chain_runs(
    template_id: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, project_id)
    runs = await list_agent_chain_runs(
        db,
        template_id=template_id,
        project_id=project_id,
        limit=limit,
    )
    # Only runs the caller may read: without a project filter the query spans every Workspace.
    return [run for run in runs if await _may_read_run(db, current_user, run)]


@router.get("/runs/{run_id}")
async def api_get_agent_chain_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await get_agent_chain_run(db, run_id=run_id)
    if not await _may_read_run(db, current_user, run):  # unreadable and missing answer alike
        raise HTTPException(status_code=404, detail="Agent chain run not found")
    return run


async def _may_read_run(db: AsyncSession, user: User, run: Any) -> bool:
    """The run's starter, or a member (with a role) of its Workspace; a run without a Workspace: its starter only."""
    from ...services.access_control import get_project_role_for_user  # noqa: PLC0415

    payload = run if isinstance(run, dict) else getattr(run, "__dict__", {})
    started_by, project_id = payload.get("started_by"), payload.get("project_id")
    if started_by and str(started_by) == str(user.id):
        return True
    return bool(project_id) and await get_project_role_for_user(db, str(user.id), str(project_id)) is not None
