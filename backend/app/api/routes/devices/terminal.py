"""Terminal API: REST and WebSocket endpoints for PTY sessions, for an active global admin only."""

from __future__ import annotations

import json
import sys

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ....models import User
from ....services.auth.admin_principal import get_current_admin_user
from ....services.data_access import as_viewer, bind_request_viewer
from ....services.error_facts import error_text

router = APIRouter(prefix="/api/v1/terminal", tags=["terminal"])


async def get_interactive_admin(request: Request, current_user: User = Depends(get_current_admin_user)) -> User:
    if getattr(request.state, "api_key_id", None):  # a leaked key must not become a shell on the host
        raise HTTPException(status_code=403, detail="interactive_login_required")
    return current_user

_IS_UNIX = sys.platform != "win32"


class CreateSessionRequest(BaseModel):
    # PTY params validated to prevent abuse
    cwd: str | None = None
    command: str | None = None
    env: dict[str, str] | None = None

    @classmethod
    def model_validate(cls, data: dict) -> CreateSessionRequest:
        # Sanitize env keys and values — reject anything suspicious
        if "env" in data and isinstance(data["env"], dict):
            clean: dict[str, str] = {}
            # Block dangerous environment variables that could compromise the PTY session
            _blocked_env_keys = frozenset({
                "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
                "LD_USE_LOAD_BIAS", "LD_ORIGIN_USAGE",
                "BASH_ENV", "ENV", "CDPATH", "GLOBIGNORE", "IFS",
                "MAIL", "MAILPATH", "HISTFILE", "HISTDIR", "HISTFILESIZE",
                "HOSTALIASES", "ENV", "BASH_ENV", "TZ", "TERMINFO", "TERMINFO_DIRS",
                "NLTK_DATA", "PYTHONPATH", "PERL5LIB", "PERLLIB", "PERL_INC",
                "RUBYLIB", "RUBYOPT", "GEM_HOME", "GEM_PATH",
                "NODE_PATH", "NODE_OPTIONS",
            })
            for k, v in data["env"].items():
                if isinstance(k, str) and isinstance(v, str):
                    key = k.strip()
                    if key and key not in _blocked_env_keys:
                        clean[key] = v.strip()
            data["env"] = clean if clean else None
        return super().model_validate(data)


async def _is_active_admin(user_id: str) -> bool:
    from ....db import core as db_core
    from ....services.admin.governance.admin_access_service import is_global_admin

    with as_viewer(user_id):
        async with db_core.async_session_factory() as db:
            user = await db.get(User, user_id)
            return bool(user is not None and user.is_active and await is_global_admin(db, user_id))


@router.get("/sessions")
async def list_sessions(current_user: User = Depends(get_interactive_admin)):
    if not _IS_UNIX:
        return {"sessions": [], "message": "PTY not available on Windows"}
    from ....services.pty import pty_manager

    return {"sessions": pty_manager.list()}


@router.post("/sessions")
async def create_session(req: CreateSessionRequest, current_user: User = Depends(get_interactive_admin)):
    if not _IS_UNIX:
        raise HTTPException(status_code=501, detail="PTY sessions are not supported on Windows")
    from ....services.pty import pty_manager

    try:
        session = await pty_manager.create(cwd=req.cwd, command=req.command, env=req.env)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Terminal session could not be started. {error_text('terminal_start_failed', e)}",
        ) from e
    return {
        "id": session.id,
        "pid": session.pid,
        "status": session.status,
        "execution_runtime": session.execution_runtime,
    }


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str, current_user: User = Depends(get_interactive_admin)):
    if not _IS_UNIX:
        raise HTTPException(status_code=501, detail="PTY sessions are not supported on Windows")
    from ....services.pty import pty_manager

    session = pty_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    pty_manager.close(session_id)
    return {"status": "closed"}


async def _open_session(websocket: WebSocket, session_id: str, token: str):
    # Only an active admin with a valid token gets a PTY session.
    from app.services.auth.tokens import verify_ws_token

    if not _IS_UNIX:
        await websocket.close(code=1011, reason="PTY not available on Windows")
        return None

    # Verify JWT token from query parameter, then the admin role of an active principal.
    try:
        user_id = await verify_ws_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return None
    if not await _is_active_admin(user_id):
        await websocket.close(code=4003, reason="Forbidden")
        return None
    bind_request_viewer(user_id)

    from ....services.pty import pty_manager

    session = pty_manager.get(session_id)
    if not session:
        await websocket.close(code=1008, reason="Session not found")
        return None
    return session


async def _forward_output(websocket: WebSocket, queue) -> None:
    exit_signal = b"\x00__EXIT__\x00"
    while True:
        try:
            data: bytes = await queue.get()
            if data == exit_signal:
                await websocket.send_text(json.dumps({"type": "exit"}))
                await websocket.close()
                return
            text = data.decode("utf-8", errors="replace")
            await websocket.send_text(json.dumps({"type": "output", "data": text}))
        except Exception:
            return


async def _forward_input(websocket: WebSocket, session_id: str) -> None:
    from ....services.pty import pty_manager

    while True:
        try:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "input":
                pty_manager.write(session_id, msg.get("data", ""))
            elif msg.get("type") == "resize":
                pty_manager.resize(session_id, int(msg.get("cols", 80)), int(msg.get("rows", 24)))
        except WebSocketDisconnect:
            return
        except Exception:
            return


@router.websocket("/sessions/{session_id}/ws")
async def session_ws(session_id: str, websocket: WebSocket, token: str = Query(...)):
    """Bidirectional WebSocket for PTY input and output."""
    session = await _open_session(websocket, session_id, token)
    if session is None:
        return

    await websocket.accept()

    if session.buffer:
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "output",
                        "data": session.buffer.decode("utf-8", errors="replace"),
                    }
                )
            )
        except Exception:
            pass

    queue = session.subscribe()

    import asyncio

    reader_task = asyncio.create_task(_forward_output(websocket, queue))
    writer_task = asyncio.create_task(_forward_input(websocket, session_id))
    done, pending = await asyncio.wait(
        [reader_task, writer_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()

    session.unsubscribe(queue)
