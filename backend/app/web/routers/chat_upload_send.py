"""Chat routes that upload files and send a chat turn."""

import mimetypes
import secrets
import uuid

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.admin.admin_panel._chat import ChatSendRequest
from app.web._helpers.workspace_artifacts import (
    _chat_upload_root,
    _path_within_root,
    _safe_upload_name,
    _workspace_artifact_url,
)

from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY
from ...db import async_session_factory, get_db
from ...http_multipart_route import BoundedFormRoute
from ...models import Session as AgentSession
from ...services.project.new_chat_workspace import new_chat_workspace
from ...services.session.turn_handoff import names_a_workflow
from ...services.session.workspace import ensure_session_workspace_root
from ...services.session.workspace_sync import sync_workspace_file_after_write
from .. import _context
from .._helpers.api_guards import _require_api_user
from .._helpers.chat_device_turn import device_chat_send, send_target
from .._helpers.chat_send_idempotency import repeated_send_response
from .._helpers.chat_turn_ack_state import _build_chat_turn_ack_state
from .._helpers.chat_turn_start import _start_chat_turn

router = APIRouter(route_class=BoundedFormRoute)


async def _upload_destination(db: AsyncSession, user, resolved_session_id: str):
    if resolved_session_id:
        session = (
            await db.execute(
                select(AgentSession).where(
                    AgentSession.id == resolved_session_id,
                    AgentSession.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        workspace_root = await ensure_session_workspace_root(db, session)
        upload_dir = (workspace_root / "uploads").resolve()
        if not _path_within_root(upload_dir, workspace_root):
            raise HTTPException(status_code=403, detail="Upload path must stay inside the workspace")
        return upload_dir, workspace_root
    bucket_id = f"draft-{secrets.token_hex(8)}"
    upload_dir = (_chat_upload_root() / bucket_id).resolve()
    if _chat_upload_root() not in upload_dir.parents and upload_dir != _chat_upload_root():
        raise HTTPException(status_code=403, detail="Upload path must stay inside the workspace")
    return upload_dir, None


async def _store_upload(
    db: AsyncSession,
    upload: UploadFile,
    *,
    upload_dir,
    workspace_root,
    resolved_session_id: str,
) -> dict[str, object]:
    safe_name = _safe_upload_name(upload.filename or "upload.bin")
    target = (upload_dir / f"{uuid.uuid4().hex}-{safe_name}").resolve()
    if upload_dir not in target.parents:
        raise HTTPException(status_code=403, detail="Upload path must stay inside the workspace")
    payload = await upload.read()
    if len(payload) > _context.MAX_CHAT_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File '{safe_name}' exceeds the 25 MB upload limit",
        )
    target.write_bytes(payload)
    media_type = upload.content_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    workspace_sync = (
        await sync_workspace_file_after_write(
            db=db,
            session_id=resolved_session_id,
            workspace_root=workspace_root,
            file_path=target,
            content_type=media_type,
        )
        if resolved_session_id
        else {"status": "skipped", "reason": "draft_upload"}
    )
    return {
        "name": safe_name,
        "path": str(target),
        "relativePath": (
            str(target.relative_to(workspace_root))
            if resolved_session_id
            else str(target.relative_to(_context.WORKSPACE_ROOT))
        ),
        "mediaType": media_type,
        "sizeBytes": target.stat().st_size,
        "url": _workspace_artifact_url(str(target)),
        "workspaceSync": workspace_sync,
    }


@router.post("/chat/api/upload")
async def chat_upload_api(
    request: Request,
    files: list[UploadFile] = File(...),
    session_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    resolved_session_id = session_id.strip()
    upload_dir, workspace_root = await _upload_destination(db, user, resolved_session_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    uploaded_files: list[dict[str, object]] = []
    for upload in files:
        uploaded_files.append(
            await _store_upload(
                db,
                upload,
                upload_dir=upload_dir,
                workspace_root=workspace_root,
                resolved_session_id=resolved_session_id,
            )
        )
        await upload.close()

    return JSONResponse({"files": uploaded_files})


@router.post("/chat/api/send")
async def chat_send_api(
    request: Request,
    payload: ChatSendRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    if (repeated := await repeated_send_response(request, db, user=user, payload=payload)) is not None:
        return repeated
    project_id = payload.project_id
    if not str(payload.session_id or "").strip():
        # A new chat starts in the named Workspace unless it is archived, else in the person's default one
        # (``services/project/new_chat_workspace``).
        project_id = await new_chat_workspace(db, user=user, project_id=project_id)
    target = await send_target(db, payload)
    named = payload.execution_target is not None and payload.execution_target.kind == "device"
    if named or not names_a_workflow(payload.workflow_key, payload.workflow_decisions):
        return await device_chat_send(request, db, user=user, payload=payload, target=target, project_id=project_id)
    # A message naming a workflow is prepared first: held for its proposal (the start card), or handed to a runner.
    request_session_factory = getattr(request.app.state, "async_session_factory", async_session_factory)
    explicit_project_id = "project_id" in getattr(payload, "model_fields_set", set())
    explicit_runtime_target_id = "runtime_target_id" in getattr(payload, "model_fields_set", set()) and bool(
        str(payload.runtime_target_id or "").strip()
    )
    explicit_thinking_level = "thinking_level" in getattr(payload, "model_fields_set", set())
    session = await _start_chat_turn(
        db=db,
        user=user,
        session_factory=request_session_factory,
        prompt=payload.prompt,
        session_id=payload.session_id,
        project_id=project_id,
        runtime_target_id=payload.runtime_target_id,
        agent_id=payload.agent_id,
        agent_type=DEFAULT_AGENT_MODE_KEY,
        workflow_key=payload.workflow_key,
        workflow_decisions=payload.workflow_decisions,
        project_id_explicit=explicit_project_id,
        runtime_target_id_explicit=explicit_runtime_target_id,
        thinking_level_explicit=explicit_thinking_level,
        thinking_level=payload.thinking_level or "light",
        idempotency_key=payload.idempotency_key,
    )
    state = await _build_chat_turn_ack_state(
        request,
        db,
        user=user,
        session=session,
        runtime_target_id=payload.runtime_target_id,
        thinking_level=payload.thinking_level or "light",
        agent_id=payload.agent_id,
        agent_type=session.agent_type or DEFAULT_AGENT_MODE_KEY,
    )
    return JSONResponse(state)
