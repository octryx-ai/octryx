"""Chat sidebar bulk actions: one request per bulk action, scopes resolved on the server."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.session.thread_bulk import apply_thread_bulk_action
from ...time_utils import utc_now
from .._helpers.api_guards import _require_admin_api, _require_api_user
from .._helpers.chat_thread_scope import MAX_BULK_IDS, ThreadScope, count_thread_scope, resolve_thread_targets

router = APIRouter()


class ThreadBulkScopeBody(BaseModel):
    project_id: str = ""
    query: str = Field(default="", max_length=200)
    as_of: datetime | None = None
    except_ids: list[str] = Field(default_factory=list, max_length=MAX_BULK_IDS)


class ThreadBulkBody(BaseModel):
    action: Literal["archive", "delete", "restore"]
    ids: list[str] = Field(default_factory=list, max_length=MAX_BULK_IDS)
    scopes: list[ThreadBulkScopeBody] = Field(default_factory=list, max_length=100)
    dry_run: bool = False


@router.post("/chat/api/threads/bulk")
async def chat_threads_bulk_api(body: ThreadBulkBody, request: Request, db: AsyncSession = Depends(get_db)):
    # Delete keeps the single-delete permission: a member gets 403 for the call, never a partial run.
    user = await (_require_admin_api if body.action == "delete" else _require_api_user)(request, db)
    scopes = [
        ThreadScope(project_id=scope.project_id, query=scope.query, as_of=scope.as_of, except_ids=scope.except_ids)
        for scope in body.scopes
    ]
    sessions, not_found_ids = await resolve_thread_targets(
        db, user=user, ids=body.ids, scopes=scopes, archived=body.action == "restore"
    )
    result = await apply_thread_bulk_action(
        db,
        user_id=user.id,
        action=body.action,
        sessions=sessions,
        not_found_ids=not_found_ids,
        dry_run=body.dry_run,
    )
    return JSONResponse(result.to_payload())


@router.get("/chat/api/thread-groups/count")
async def chat_thread_group_count_api(
    request: Request,
    project_id: str = "",
    q: str = "",
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    # The server clock fixes the scope's as_of, so the count and a later bulk call cover the same chats.
    as_of = utc_now()
    scope = ThreadScope(project_id=str(project_id or "").strip(), query=q[:200], as_of=as_of)
    count = await count_thread_scope(db, user=user, scope=scope)
    return JSONResponse({"projectId": scope.project_id, "count": count, "asOf": as_of.isoformat() + "Z"})
