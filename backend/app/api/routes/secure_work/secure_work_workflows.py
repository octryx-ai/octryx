"""Workflows of the Secure Work task list: list, create, update, deactivate, activate. The services enforce the
Workspace scope (``services/secure_work/workflow_access.py``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.secure_work import require_work_operator, require_work_reader
from ....services.secure_work.workflow_lifecycle import set_workflow_active, update_workflow_definition
from ....services.secure_work.workflow_mapping import create_workflow_definition, list_workflow_definitions
from ._secure_work_scope import require_secure_work_scope

router = APIRouter(
    prefix="/api/v1/secure-work", tags=["secure-work"], dependencies=[Depends(require_secure_work_scope)]
)


@router.get("/workflows")
async def get_workflows(
    project_id: str | None = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    items = await list_workflow_definitions(
        db, project_id=(project_id or "").strip() or None, include_inactive=include_inactive, current_user=current_user
    )
    return {"items": items}


@router.post("/workflows")
async def post_workflow(
    payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await require_work_operator(db, current_user)
    result = await create_workflow_definition(db, current_user=current_user, payload=payload)
    await db.commit()
    return result


@router.put("/workflows/{workflow_id}")
async def put_workflow(
    workflow_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await update_workflow_definition(db, workflow_id=workflow_id, current_user=current_user, payload=payload)
    await db.commit()
    return result


@router.post("/workflows/{workflow_id}/deactivate")
async def deactivate_workflow(
    workflow_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await set_workflow_active(db, workflow_id=workflow_id, current_user=current_user, active=False,
                                       expected_updated_at=(payload or {}).get("updated_at"))
    await db.commit()
    return result


@router.post("/workflows/{workflow_id}/activate")
async def activate_workflow(
    workflow_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    result = await set_workflow_active(db, workflow_id=workflow_id, current_user=current_user, active=True,
                                       expected_updated_at=(payload or {}).get("updated_at"))
    await db.commit()
    return result
