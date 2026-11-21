"""Call monitoring/debugging panel API endpoints.

Exposes live in-memory call state (active calls, transcript segments,
enrollment sessions, playback locks) for real-time debugging via the admin UI.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.error_facts import error_facts, error_text
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.call_history import load_call_history, read_call_log_lines
from app.web._helpers.call_monitor import build_call_events_payload, build_live_calls_payload

router = APIRouter()


@router.get("/chat/api/panel/calls/live")
async def panel_live_calls(request: Request, db: AsyncSession = Depends(get_db)):
    """Return live in-memory state of all active Teams calls.

    This is used by the call monitoring page to show real-time call state:
    - Active calls and their metadata
    - Transcript segments per call
    - Whether bot is currently speaking
    - Enrollment sessions in progress
    - Recording queue status
    """
    await _require_admin_api(request, db)
    return JSONResponse(build_live_calls_payload())


@router.get("/chat/api/panel/calls/{call_id}/events")
async def panel_call_events(call_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Return the message history from the DB session for a specific call.

    Works for both live calls (from memory) and ended calls (from DB).
    """
    await _require_admin_api(request, db)
    return JSONResponse(await build_call_events_payload(db, call_id))


@router.get("/chat/api/panel/calls/log")
async def panel_call_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
    call_id: str | None = None,
    limit: int = 150,
):
    """Return call-debug lines from the uvicorn log, optionally filtered by call_id.

    Args:
        call_id: If provided, only return log lines containing this call ID.
        limit: Max lines to return (default 150).
    """
    await _require_admin_api(request, db)
    bounded_limit = max(1, min(int(limit or 150), 500))
    lines = read_call_log_lines(call_id, bounded_limit)
    return JSONResponse({"lines": lines, "total": len(lines), "call_id": call_id})


@router.get("/chat/api/panel/calls/history")
async def panel_call_history(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    search: str | None = None,
):
    """Return recent calls from the DB (both active and completed).

    Supports searching by call_id, db_session_id, caller name, or date (YYYY-MM-DD).
    """
    await _require_admin_api(request, db)

    from ...models import Session as OctryxSession
    from ...services.teams_calling.call_session_state import _call_states

    bounded_limit = max(1, min(limit, 200))
    search_term = (search or "").strip().lower()
    try:
        calls_info = await load_call_history(
            db,
            session_model=OctryxSession,
            call_states=_call_states,
            search_term=search_term,
            bounded_limit=bounded_limit,
        )
    except Exception as e:
        return JSONResponse(
            {
                "calls": [],
                "error": f"Call history could not be loaded. {error_text('call_history_failed', e)}",
                **error_facts("call_history_failed", e),
            }
        )
    return JSONResponse({"calls": calls_info[:bounded_limit]})
