from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import FlowDefinition, User
from ....services.access_control import require_existing_workspace
from ....services.auth import get_current_user
from ....services.flow_definitions import create_flow_definition, list_flow_definitions, validate_flow_definition
from ....services.flow_draft_service import save_flow_draft
from ....services.notification_delivery import require_admin_user
from ....services.workflow_generation import generate_workflow_draft_from_session
from ....services.workflow_runs.fragments.store import is_composite, is_fragment, validate_source, without_seed_markers
from ....services.workflow_runs.graph import is_phased_definition
from .flow_definition_state import router as state_router
from .flow_definition_versions import router as versions_router

router = APIRouter(prefix="/api/v1/flows", tags=["flows"])


@router.get("")
async def get_flow_definitions(
    project_id: str | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return {
        "items": await list_flow_definitions(
            db,
            project_id=(project_id or "").strip() or None,
            include_inactive=include_inactive,
            limit=limit,
        )
    }


@router.post("")
async def post_flow_definition(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    definition = payload.get("definition")
    if (is_fragment(definition) or is_composite(definition) or is_phased_definition(definition)) and isinstance(
            payload.get("runtime_settings"), dict):
        # Only the shipped seeders mark a phased version as a seed (four-eyes exemption, seed pins).
        payload = {**payload, "runtime_settings": without_seed_markers(payload["runtime_settings"])}
    result = await create_flow_definition(db, current_user=current_user, payload=payload)
    await db.commit()
    return result


@router.post("/{flow_id}/drafts")
async def post_flow_draft(
    flow_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await save_flow_draft(db, flow_id=flow_id, current_user=current_user, payload=payload)
    await db.commit()
    return result


@router.post("/validate")
async def post_validate_flow_definition(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    await require_existing_workspace(db, current_user.id, str(payload.get("project_id") or "").strip() or None)
    definition = payload.get("definition") if "definition" in payload else payload
    if not isinstance(definition, dict):
        raise HTTPException(status_code=422, detail="definition must be an object")
    # A composite is resolved against an explicit flow_id or project_id, never a guessed one.
    context = payload if "definition" in payload else {}
    if is_composite(definition):
        # A composite source is resolved against its pins and validated as composed (with ``composition``).
        report, compiled = await validate_source(db, definition, project_id=await _validation_scope(db, context))
        if not report.get("valid"):
            raise HTTPException(status_code=422, detail=report)
        return report
    return validate_flow_definition(definition)


async def _validation_scope(db: AsyncSession, context: dict) -> str | None:
    project_id = str(context.get("project_id") or "").strip() or None
    flow_id = str(context.get("flow_id") or "").strip()
    if project_id is None and flow_id:
        flow = await db.get(FlowDefinition, flow_id)
        project_id = flow.project_id if flow is not None else None
    return project_id


@router.post("/generate-from-session/{session_id}")
async def post_generate_flow_from_session(
    session_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await generate_workflow_draft_from_session(
        db,
        session_id=session_id,
        current_user=current_user,
        payload=payload or {},
    )
    await db.commit()
    return result


# Included after the routes above so the registration order stays the same.
router.include_router(versions_router)
router.include_router(state_router)
