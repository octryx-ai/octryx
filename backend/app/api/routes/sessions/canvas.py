import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import decode_session_stream_token, decode_token, get_current_user
from ....services.canvas import canvas_manager
from ....services.data_access import bind_request_viewer
from ....services.session.collaboration import get_session_access_role, require_session_access

router = APIRouter(prefix="/api/v1/canvas", tags=["canvas"])
logger = logging.getLogger(__name__)


async def _authorize_canvas_websocket(
    *,
    session_id: str,
    ws: WebSocket,
    db: AsyncSession,
) -> str | None:
    token = str(ws.query_params.get("token") or "").strip()
    user_id: str
    if token:
        try:
            user_id, token_session_id = decode_session_stream_token(token)
        except HTTPException as exc:
            await ws.close(code=1008, reason=str(exc.detail))
            return None
        if token_session_id != session_id:
            await ws.close(code=1008, reason="Session stream token does not match requested session")
            return None
    else:
        cookie_token = str(ws.cookies.get("access_token") or "").strip()
        if not cookie_token:
            await ws.close(code=1008, reason="Authentication required")
            return None
        try:
            user_id = decode_token(cookie_token)
        except HTTPException as exc:
            await ws.close(code=1008, reason=str(exc.detail))
            return None

    bind_request_viewer(user_id)
    access_role = await get_session_access_role(db, session_id=session_id, user_id=user_id)
    if access_role is None:
        await ws.close(code=1008, reason="Session not found")
        return None
    return access_role


@router.post("/sessions/{session_id}")
async def create_canvas(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_session_access(db, session_id=session_id, user_id=current_user.id)
    canvas = canvas_manager.get_or_create(session_id)
    return {"canvas_id": canvas.id, "session_id": canvas.session_id}


@router.get("/sessions/{session_id}")
async def get_canvas(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_session_access(db, session_id=session_id, user_id=current_user.id)
    canvas = canvas_manager.get_canvas_for_session(session_id)
    if not canvas:
        raise HTTPException(404, "No canvas for this session")
    return {"canvas_id": canvas.id, "elements": canvas.elements}


@router.websocket("/sessions/{canvas_id}/ws")
async def canvas_ws(
    canvas_id: str,
    ws: WebSocket,
    db: AsyncSession = Depends(get_db),
):
    canvas = canvas_manager.get_canvas(canvas_id)
    if not canvas:
        await ws.close(code=4004, reason="Canvas not found")
        return

    access_role = await _authorize_canvas_websocket(session_id=canvas.session_id, ws=ws, db=db)
    if access_role is None:
        return

    await canvas_manager.connect(canvas_id, ws)
    try:
        while True:
            data = await ws.receive_json()
            if access_role == "observer" and str(data.get("type") or "").strip().lower() in {"draw", "clear", "undo"}:
                await ws.close(code=1008, reason="Contributor access required")
                break
            await canvas_manager.handle_message(canvas_id, ws, data)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Canvas websocket failed for canvas_id=%s", canvas_id)
        try:
            await ws.close(code=1011, reason="Canvas websocket error")
        except Exception:
            pass
    finally:
        await canvas_manager.disconnect(canvas_id, ws)
