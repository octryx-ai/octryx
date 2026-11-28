"""Auto-extracted router module: chat_main."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session.turn_tasks import effective_session_status as _effective_session_status

from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY
from ...db import get_db
from ...models import Session as AgentSession
from ...services.access_control import require_project_access
from ...services.observability.run_owner_view import run_details_for_user
from ...services.session.artifact_visibility import load_user_turn_trace
from ...services.session.run_state import RUN_STATUS_AWAITING_SUBAGENTS, RUN_STATUS_IN_PROGRESS
from ...services.session.turn_calls import turn_calls
from ...services.workflow_routing.explicit_selection import list_published_workflow_definitions
from ...services.workflow_routing.proposal_policy import workflow_proposals_enabled
from .._helpers._chat_state_builder import _build_chat_state
from .._helpers.api_guards import _chat_app_index_path, _chat_app_missing_response, _require_api_user
from .._helpers.auth import _require_user
from .._helpers.chat_turn_ack_state import _build_chat_turn_ack_state
from .._helpers.serialization import _effective_session_run_status
from .._helpers.workspace import _serialize_turn_trace
from .chat_artifacts import router as chat_artifacts_router

router = APIRouter()
logger = logging.getLogger(__name__)

def _chat_bootstrap_response(
    state: dict,
    *,
    kind: str,
    started_at: float,
    session_id: str | None,
) -> JSONResponse:
    response = JSONResponse(state)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    payload_bytes = len(response.body or b"")
    response.headers["X-Chat-Bootstrap-Kind"] = kind
    response.headers["X-Chat-Bootstrap-Elapsed-Ms"] = str(elapsed_ms)
    response.headers["X-Chat-Bootstrap-Payload-Bytes"] = str(payload_bytes)
    logger.info(
        "chat.bootstrap.response",
        extra={
            "kind": kind,
            "elapsed_ms": elapsed_ms,
            "payload_bytes": payload_bytes,
            "session_id": session_id or "",
            "selected_session_id": str((state.get("selectedSession") or {}).get("id") or ""),
            "selected_session_status": str((state.get("selectedSession") or {}).get("status") or ""),
            "selected_run_status": str(
                (state.get("selectedSession") or {}).get("runStatus")
                or (state.get("selectedSession") or {}).get("run_status")
                or ""
            ),
            "active_thread_group_count": len(state.get("activeThreadGroups") or []),
            "archived_thread_group_count": len(state.get("archivedThreads") or []),
            "selected_message_count": len(state.get("selectedMessages") or []),
            "right_panel_event_count": len(state.get("rightPanelEvents") or []),
        },
    )
    return response


def _should_use_running_ack_state(session: AgentSession) -> bool:
    session_status = _effective_session_status(session)
    if session_status in {"running", "awaiting_subagents"}:
        return True
    run_status = _effective_session_run_status(session)
    return run_status in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_AWAITING_SUBAGENTS}


async def _ensure_own_private_workspace(db: AsyncSession, user) -> None:
    from ...services.project.private_workspace import (
        ensure_private_workspace,
        owned_private_workspace,
        sync_template_policy,
    )

    own = await owned_private_workspace(db, str(user.id))
    if own is None:  # everybody gets theirs on first use
        await ensure_private_workspace(db, user)
        await db.commit()
    elif await sync_template_policy(db, own):  # the admins' defaults (default Workspace's policy) apply here too
        await db.commit()


@router.api_route("/chat", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def chat_page(
    request: Request,
    session_id: str | None = None,
    project_id: str = "",
    runtime_target_id: str = "",
    agent_id: str = "",
    new: bool = False,
    db: AsyncSession = Depends(get_db),
):
    request_path = request.url.path.rstrip("/")
    if request_path == "/admin/chat":
        query = request.url.query
        return RedirectResponse(url=f"/chat{f'?{query}' if query else ''}", status_code=307)
    try:
        await _require_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/chat/login", status_code=303)
    index_path = _chat_app_index_path()
    if not index_path.exists():
        return _chat_app_missing_response()
    return FileResponse(
        index_path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/chat/api/bootstrap")
async def chat_bootstrap_api(
    request: Request,
    session_id: str | None = None,
    project_id: str = "",
    runtime_target_id: str = "",
    agent_id: str = "",
    agent_type: str = "",
    new: bool = False,
    db: AsyncSession = Depends(get_db),
):
    started_at = time.perf_counter()
    user = await _require_api_user(request, db)
    await _ensure_own_private_workspace(db, user)
    if session_id and not new:
        selected_session = (
            await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
        ).scalar_one_or_none()
        if selected_session and _should_use_running_ack_state(selected_session):
            metadata = dict(selected_session.metadata_ or {})
            state = await _build_chat_turn_ack_state(
                request,
                db,
                user=user,
                session=selected_session,
                runtime_target_id=str(metadata.get("runtime_target_id") or runtime_target_id or ""),
                thinking_level=str(metadata.get("thinking_level") or "light"),
                agent_id=str(metadata.get("agent_definition_id") or agent_id or ""),
                agent_type=str(selected_session.agent_type or agent_type or DEFAULT_AGENT_MODE_KEY),
            )
            return _chat_bootstrap_response(
                state,
                kind="running_ack",
                started_at=started_at,
                session_id=session_id,
            )
    state = await _build_chat_state(
        request,
        db,
        user=user,
        session_id=session_id,
        project_id=project_id,
        runtime_target_id=runtime_target_id,
        agent_id=agent_id,
        agent_type=agent_type,
        new_thread=new,
    )
    return _chat_bootstrap_response(
        state,
        kind="full",
        started_at=started_at,
        session_id=session_id,
    )


@router.get("/chat/api/workflows")
async def chat_workflows_api(
    request: Request,
    project_id: str = "",
    include_hidden: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Published workflows selectable via ChatSendRequest.workflow_key (the published phased workflows)."""
    user = await _require_api_user(request, db)
    scope = project_id.strip() or None
    await require_project_access(db, user.id, scope)
    if include_hidden:
        from ...services.admin.governance.admin_access_service import is_global_admin

        if not await is_global_admin(db, user.id):
            raise HTTPException(status_code=403, detail="include_hidden is for admins only")
    definitions = await list_published_workflow_definitions(db, project_id=scope, include_hidden=include_hidden)
    return JSONResponse(
        {
            "workflows": definitions,
            # With proposals on, the client offers "Automatic" and an explicit "No workflow" choice.
            "workflow_proposal_enabled": await workflow_proposals_enabled(db, project_id.strip() or None),
        }
    )


@router.get("/chat/api/turn-traces/{trace_id}")
async def chat_turn_trace_api(request: Request, trace_id: str, db: AsyncSession = Depends(get_db)):
    user = await _require_api_user(request, db)
    trace = await load_user_turn_trace(db, user_id=user.id, trace_id=trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Turn trace not found")
    payload = await run_details_for_user(db, user.id, _serialize_turn_trace(trace))
    # An answer's trace lists the turn's model calls; each call's content loads from this route when opened.
    return JSONResponse({**(payload or {}), **await turn_calls(db, trace, user_id=user.id)})


router.include_router(chat_artifacts_router)
