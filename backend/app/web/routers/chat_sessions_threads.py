"""Chat session lifecycle, message, and workspace routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.admin.admin_panel._chat import ChatContinueRequest
from app.services.session.turn_tasks import effective_session_status as _effective_session_status

from ...db import get_db
from ...models import User
from ...services.devices.agent_runtime import chat_target_for, stop_session_jobs
from ...services.devices.chat_turn import device_thread_target
from ...services.session.analysis_export import build_session_analysis_export
from ...services.session.lifecycle import archive_session_tree, restore_session_tree, set_session_pinned_state
from ...services.session.markdown_export import build_session_markdown_export
from ...services.session.pdf_export import build_session_pdf_export
from ...services.session.tree_cleanup import cleanup_session_descendants, collect_session_descendants
from ...services.session.turn_stop import stop_session_turn
from ...services.session.workspace import (
    delete_session_workspace,
)
from .._helpers._chat_state_builder import _build_chat_state
from .._helpers.api_guards import _require_admin_api, _require_api_user
from .._helpers.chat_device_turn import device_chat_turn
from .._helpers.chat_session_thread_lookup import get_owned_chat_session
from .._helpers.serialization import _resolve_root_session
from .chat_session_workspace import router as chat_session_workspace_router

router = APIRouter()


@router.post("/chat/api/sessions/{session_id}/continue")
async def chat_continue_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    if session.status == "archived":
        raise HTTPException(status_code=409, detail="Archived: restore it from Archived chats in the list")
    if _effective_session_status(session) == "running":
        raise HTTPException(status_code=409, detail="This thread is already running")

    payload = (
        ChatContinueRequest.model_validate(await request.json())
        if request.headers.get("content-type", "").startswith("application/json")
        else ChatContinueRequest()
    )
    prompt = payload.prompt.strip()
    if not prompt:
        prompt = "Continue from the previous failure and keep working in this same thread. Do not restart from scratch."

    target = device_thread_target(session) or await chat_target_for(db, session.id)
    return await device_chat_turn(request, db, user=user, prompt=prompt, target=target, session_id=session.id,
                                  project_id=session.project_id, thinking_level=payload.thinking_level)


@router.post("/chat/api/sessions/{session_id}/compact")
async def chat_compact_session_api(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from .._helpers.chat_device_turn import device_chat_compact

    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    return await device_chat_compact(request, db, user=user, session=session)


@router.post("/chat/api/sessions/{session_id}/stop")
async def chat_stop_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    if session.status != "running":
        # A thread on a device or server runner is never ``running`` here: its turn is the device job's.
        if await stop_session_jobs(db, session_id=session.id, actor_id=user.id):
            await db.commit()
        state = await _build_chat_state(request, db, user=user, session_id=session.id)
        return JSONResponse(state)

    await stop_session_turn(db, session)

    user_id = user.id
    current_session_id = session.id
    await db.rollback()
    fresh_user = await db.get(User, user_id)
    state = await _build_chat_state(request, db, user=fresh_user or user, session_id=current_session_id)
    return JSONResponse(state)


@router.post("/chat/api/sessions/{session_id}/archive")
async def chat_archive_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    await archive_session_tree(db, session_id=session.id, user_id=user.id)
    await db.commit()
    # The client reloads its list once; building a full chat state here was discarded work.
    return JSONResponse({"ok": True, "id": session.id})


@router.post("/chat/api/sessions/{session_id}/restore")
async def chat_restore_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    await restore_session_tree(db, session_id=session.id, user_id=user.id)
    await db.commit()
    state = await _build_chat_state(request, db, user=user, session_id=session.id)
    return JSONResponse(state)


@router.post("/chat/api/sessions/{session_id}/pin")
async def chat_pin_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    set_session_pinned_state(session, True)
    await db.commit()
    state = await _build_chat_state(request, db, user=user, session_id=session.id)
    return JSONResponse(state)


@router.post("/chat/api/sessions/{session_id}/unpin")
async def chat_unpin_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    set_session_pinned_state(session, False)
    await db.commit()
    state = await _build_chat_state(request, db, user=user, session_id=session.id)
    return JSONResponse(state)


@router.get("/chat/api/sessions/{session_id}/export")
async def chat_export_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    export = await build_session_markdown_export(db, session_id=session_id, user_id=user.id, exported_by=user)
    headers = {"Content-Disposition": f'attachment; filename="{export.filename}"'}
    return Response(content=export.content, media_type="text/markdown; charset=utf-8", headers=headers)


@router.get("/chat/api/sessions/{session_id}/export.pdf")
async def chat_export_session_pdf_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    export = await build_session_pdf_export(db, session_id=session_id, user_id=user.id, exported_by=user)
    headers = {"Content-Disposition": f'attachment; filename="{export.filename}"'}
    return Response(content=export.content, media_type="application/pdf", headers=headers)


@router.get("/chat/api/sessions/{session_id}/export.analysis.json")
async def chat_export_session_analysis_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    export = await build_session_analysis_export(db, session_id=session_id, user_id=user.id, exported_by=user)
    headers = {"Content-Disposition": f'attachment; filename="{export.filename}"'}
    return Response(content=export.content, media_type="application/json; charset=utf-8", headers=headers)


@router.delete("/chat/api/sessions/{session_id}")
async def chat_delete_session_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    root_session = await _resolve_root_session(db, session)
    root_session_id = root_session.id if root_session else session.id
    descendant_session_ids = await collect_session_descendants(db, root_session_id)
    for descendant_session_id in descendant_session_ids:
        await delete_session_workspace(db, descendant_session_id)
    await cleanup_session_descendants(db, root_session_id)
    await db.commit()
    state = await _build_chat_state(request, db, user=user, new_thread=True)
    return JSONResponse(state)


router.include_router(chat_session_workspace_router)
