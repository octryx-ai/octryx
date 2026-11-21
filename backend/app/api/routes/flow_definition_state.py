"""Archive, active switch, composition and detail of one flow definition.

Included last into the ``/api/v1/flows`` router by ``flow_definitions.py``: ``GET /{flow_id}`` matches any single
segment, so it is registered after every other route of that prefix.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import FlowDefinitionVersion, User
from ...services.auth import get_current_user
from ...services.flow_definitions import archive_flow_definition, get_flow_definition
from ...services.notification_delivery import require_admin_user
from ...services.workflow_runs.fragments.store import composition_view

router = APIRouter()


@router.post("/{flow_id}/archive")
async def post_archive_flow_definition(
    flow_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await archive_flow_definition(db, flow_id=flow_id, current_user=current_user)
    await db.commit()
    return result


@router.post("/{flow_id}/active")
async def post_flow_definition_active(
    flow_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch a workflow on or off (``{"active": true|false}``): an optional shipped workflow is off until an admin
    switches it on (``flow_activation``)."""
    from ...services.flow_activation import set_flow_active

    await require_admin_user(db, current_user)
    active = payload.get("active") if isinstance(payload, dict) else None
    if not isinstance(active, bool):
        raise HTTPException(status_code=422, detail={"reason": "active_required",
                                                     "message": "Send active: true or false."})
    result = await set_flow_active(db, flow_id=flow_id, active=active, current_user=current_user)
    await db.commit()
    return result


@router.get("/{flow_id}/versions/{version_id}/composition")
async def get_flow_version_composition(
    flow_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The composite version's source, pinned fragments and per-node provenance (read-only)."""
    await require_admin_user(db, current_user)
    version = await db.get(FlowDefinitionVersion, version_id)
    if version is None or version.flow_id != flow_id:
        raise HTTPException(status_code=404, detail={"reason": "flow_version_not_found"})
    view = composition_view(version)
    if view is None:
        raise HTTPException(status_code=404, detail={"reason": "composition_not_found"})
    return view


@router.get("/{flow_id}")
async def get_flow_definition_detail(
    flow_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await get_flow_definition(db, flow_id=flow_id)
