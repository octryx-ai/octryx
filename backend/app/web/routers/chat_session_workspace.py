"""Chat routes for a session's messages and its workspace files."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.runtime_options import list_chat_runtime_options
from app.web._helpers.api_guards import _require_api_user

from ...db import get_db
from ...models import Approval
from ...services.change_preview import (
    list_change_previews_by_approval_id,
    serialize_change_preview,
)
from ...services.session.workspace import (
    clean_session_workspace,
    create_workspace_directory,
    delete_workspace_paths,
    move_workspace_paths,
    rename_workspace_path,
    resolve_session_workspace_root,
    search_session_workspace_entries,
    serialize_session_workspace_children,
)
from .._helpers.approval_serialization import _serialize_approval, approver_names
from .._helpers.chat_session_thread_lookup import get_owned_chat_session
from .._helpers.chat_state import CHAT_MESSAGE_PAGE_SIZE
from .._helpers.workspace import _load_chat_message_page, _serialize_session_workspace_changes
from .._helpers.workspace_tree_payloads import (
    build_session_workspace_response,
    build_workspace_search_response,
    build_workspace_tree_response,
)

router = APIRouter()


async def _serialize_workspace_approval_changes(
    db: AsyncSession,
    approvals: list[Approval],
) -> list[dict]:
    preview_by_approval_id = await list_change_previews_by_approval_id(db, [approval.id for approval in approvals])
    approver_name_by_id = await approver_names(db, approvals)
    serialized_approvals = [
        _serialize_approval(
            approval,
            change_preview=serialize_change_preview(preview_by_approval_id.get(approval.id)),
            approver_name_by_id=approver_name_by_id,
        )
        for approval in approvals
    ]
    return _serialize_session_workspace_changes(serialized_approvals)


@router.get("/chat/api/sessions/{session_id}/messages")
async def chat_session_messages_api(
    session_id: str,
    request: Request,
    before_message_id: str | None = None,
    limit: int = CHAT_MESSAGE_PAGE_SIZE,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    runtime_options = await list_chat_runtime_options(db)
    runtime_label_by_id = {option["value"]: option["label"] for option in runtime_options}
    selected_runtime_target_id = str((session.metadata_ or {}).get("runtime_target_id") or "")
    selected_runtime_label = runtime_label_by_id.get(
        selected_runtime_target_id,
        str((session.metadata_ or {}).get("runtime_label") or "").strip() or runtime_label_by_id.get("", ""),
    )
    workspace_root = await resolve_session_workspace_root(db, session, create=False)
    messages, has_more = await _load_chat_message_page(
        db,
        session=session,
        user=user,
        workspace_root=workspace_root,
        selected_runtime_label=selected_runtime_label,
        limit=limit,
        before_message_id=before_message_id,
    )
    return JSONResponse({"messages": messages, "hasMore": has_more})


@router.get("/chat/api/sessions/{session_id}/workspace")
async def chat_session_workspace_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    approvals = (
        (
            await db.execute(
                select(Approval).where(Approval.session_id == session.id).order_by(Approval.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    workspace_root = await resolve_session_workspace_root(db, session)
    workspace_files = serialize_session_workspace_children(workspace_root, relative_path="")
    payload = build_session_workspace_response(
        workspace_root=workspace_root,
        entries=workspace_files,
        changes=await _serialize_workspace_approval_changes(db, approvals),
    )
    return JSONResponse(payload)


@router.get("/chat/api/sessions/{session_id}/workspace/tree")
async def chat_session_workspace_tree_api(
    session_id: str,
    request: Request,
    path: str = "",
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    workspace_root = await resolve_session_workspace_root(db, session)
    try:
        entries = serialize_session_workspace_children(workspace_root, relative_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail="Workspace path is not a directory") from exc
    return JSONResponse(build_workspace_tree_response(relative_path=path, entries=entries))


@router.get("/chat/api/sessions/{session_id}/workspace/search")
async def chat_session_workspace_search_api(
    session_id: str,
    request: Request,
    q: str,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    workspace_root = await resolve_session_workspace_root(db, session)
    entries = search_session_workspace_entries(workspace_root, query=q, limit=limit)
    return JSONResponse(build_workspace_search_response(query=q, entries=entries))


@router.post("/chat/api/sessions/{session_id}/workspace/folders")
async def chat_session_workspace_create_folder_api(
    session_id: str,
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    relative_path = str(payload.get("path") or "").strip()
    if not relative_path:
        raise HTTPException(status_code=400, detail="path is required")
    try:
        created = await create_workspace_directory(db, session_id, relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "path": str(created)})


@router.post("/chat/api/sessions/{session_id}/workspace/rename")
async def chat_session_workspace_rename_api(
    session_id: str,
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    try:
        renamed = await rename_workspace_path(
            db,
            session_id,
            str(payload.get("path") or "").strip(),
            str(payload.get("new_name") or "").strip(),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace path not found") from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "path": str(renamed)})


@router.post("/chat/api/sessions/{session_id}/workspace/move")
async def chat_session_workspace_move_api(
    session_id: str,
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    paths = [str(item).strip() for item in payload.get("paths") or [] if str(item).strip()]
    target_directory = str(payload.get("target_directory") or "").strip()
    if not paths:
        raise HTTPException(status_code=400, detail="paths are required")
    try:
        moved = await move_workspace_paths(db, session_id, paths, target_directory)
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "moved": [str(item) for item in moved]})


@router.post("/chat/api/sessions/{session_id}/workspace/delete")
async def chat_session_workspace_delete_api(
    session_id: str,
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    paths = [str(item).strip() for item in payload.get("paths") or [] if str(item).strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="paths are required")
    try:
        deleted = await delete_workspace_paths(db, session_id, paths)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "deleted": deleted})


@router.post("/chat/api/sessions/{session_id}/workspace/clean")
async def chat_session_workspace_clean_api(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    await get_owned_chat_session(db, session_id=session_id, user_id=user.id)
    return JSONResponse(await clean_session_workspace(db, session_id))
