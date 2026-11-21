"""Selected-session view for a chat switch (the bootstrap's selected-session keys, without the workspace)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.web._helpers.api_guards import _require_api_user

from ...db import get_db
from .._helpers.chat_session_view import build_chat_session_view

router = APIRouter()


@router.get("/chat/api/sessions/{session_id}/view")
async def chat_session_view_api(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    started_at = time.perf_counter()
    user = await _require_api_user(request, db)
    response = JSONResponse(await build_chat_session_view(db, user=user, session_id=session_id))
    response.headers["X-Chat-View-Elapsed-Ms"] = str(int((time.perf_counter() - started_at) * 1000))
    return response
