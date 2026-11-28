"""``/api/v1/phased-workflows``: the Workflows list and the editor of workflows that run in phases (admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.notification_delivery import require_admin_user
from ....services.workflow_runs.designer_catalog import designer_catalog
from ....services.workflow_runs.overview import workflows_overview
from ....services.workflow_runs.phased_editor import (
    create_phased_workflow,
    phase_graph_view,
    phased_view,
    preview_phase_graph,
    save_phase_graph,
    save_phased_definition,
    save_phased_layout,
)

router = APIRouter(prefix="/api/v1/phased-workflows", tags=["phased-workflows"])


# Before ``/{flow_id}``: "overview" is no workflow id.
@router.get("/overview")
async def get_workflows_overview(
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The Workflows page: phased workflows and flow graphs with class, scope, use, status and last change."""
    await require_admin_user(db, current_user)
    return await workflows_overview(
        db, project_id=(project_id or "").strip() or None, include_inactive=include_inactive
    )


# Before ``/{flow_id}``: "catalog" is no workflow id.
@router.get("/catalog")
async def get_designer_catalog(
    project_id: str | None = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """What the designer's side panel offers: agents, tools, check types, workflows, platform actions, values."""
    await require_admin_user(db, current_user)
    return await designer_catalog(db, project_id=(project_id or "").strip() or None)


@router.post("")
async def post_phased_workflow(
    payload: dict | None = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """A new workflow that runs in phases: a draft with Start → End."""
    await require_admin_user(db, current_user)
    result = await create_phased_workflow(db, user=current_user, body=payload if isinstance(payload, dict) else {})
    await db.commit()
    return result


@router.get("/{flow_id}")
async def get_phased_workflow(
    flow_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await require_admin_user(db, current_user)
    return await phased_view(db, flow_id, user_id=current_user.id)


@router.post("/{flow_id}/layout")
async def post_phased_layout(
    flow_id: str, payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Where the designer draws the boxes: saved as a new draft version (never published here)."""
    await require_admin_user(db, current_user)
    result = await save_phased_layout(db, flow_id, user=current_user, body=payload)
    await db.commit()
    return result


@router.post("/{flow_id}/definition")
async def post_phased_definition(
    flow_id: str, payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """The designer's whole definition as a new draft version, stored with its validation report (never published)."""
    await require_admin_user(db, current_user)
    result = await save_phased_definition(db, flow_id, user=current_user, body=payload)
    await db.commit()
    return result


@router.get("/{flow_id}/phases/{node_id}/graph")
async def get_phase_graph(
    flow_id: str, node_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await require_admin_user(db, current_user)
    return await phase_graph_view(db, flow_id, node_id)


@router.post("/{flow_id}/phases/{node_id}/graph/preview")
async def post_phase_graph_preview(
    flow_id: str, node_id: str, payload: dict, current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await preview_phase_graph(db, flow_id, node_id, payload)


@router.post("/{flow_id}/phases/{node_id}/graph")
async def post_phase_graph(
    flow_id: str, node_id: str, payload: dict, current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await save_phase_graph(db, flow_id, node_id, user=current_user, body=payload)
    await db.commit()
    return result
