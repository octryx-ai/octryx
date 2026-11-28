"""Chat routes that list and resolve actions on Office artifacts (the resolved prompt becomes a draft)."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from .._helpers.api_guards import _require_api_user, _resolve_user_artifact_context
from .chat_upload_send import router as chat_upload_send_router

router = APIRouter()


@router.get("/chat/api/artifact-actions")
async def chat_artifact_actions_api(
    request: Request,
    path: str,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    from ...services.office.documents import (
        is_office_document,
        list_office_actions_for_path,
        resolve_workspace_path,
    )

    resolved, workspace_root = await _resolve_user_artifact_context(db, user, path)
    resolved = resolve_workspace_path(workspace_root, str(resolved))
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not is_office_document(resolved):
        raise HTTPException(status_code=400, detail="Actions are only available for Office artifacts")
    return JSONResponse(list_office_actions_for_path(resolved))


async def _resolve_requested_office_action(db: AsyncSession, user, payload: dict) -> dict:
    from ...services.office.documents import (
        is_office_document,
        resolve_office_action,
        resolve_workspace_path,
    )

    path = str(payload.get("path") or "").strip()
    action_id = str(payload.get("action_id") or "").strip()
    mode = str(payload.get("mode") or "tool_plan").strip()
    if not path or not action_id:
        raise HTTPException(status_code=400, detail="path and action_id are required")
    resolved, workspace_root = await _resolve_user_artifact_context(db, user, path)
    resolved = resolve_workspace_path(workspace_root, str(resolved))
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not is_office_document(resolved):
        raise HTTPException(status_code=400, detail="Actions are only available for Office artifacts")
    try:
        return await resolve_office_action(db, resolved, action_id=action_id, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chat/api/artifact-actions/resolve")
async def chat_artifact_action_resolve_api(
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    return JSONResponse(await _resolve_requested_office_action(db, user, payload))


router.include_router(chat_upload_send_router)
