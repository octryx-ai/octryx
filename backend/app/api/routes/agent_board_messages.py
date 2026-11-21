"""Agent message board REST for the UI. Transport only; rules live in ``services/agent_board``.

Mounted under ``/api/v1/agent-board`` by ``agent_board.py``. Every Workspace-scoped answer carries
``viewer: {user_id, can_admin}`` (what the UI may offer); a non-member gets 404 like a missing message.

- ``GET /messages?project_id=&cursor=&work_item_id=&kind=&agent_hash=&limit=`` — newest first, envelopes
  with ``acks``, ``next_cursor``.
- ``GET /messages/{id}/thread`` — ``{root, replies[]}``.
- ``POST /messages/{id}/decision {option?, text?}`` — ``{decision}``; 403 when not allowed, 409
  ``already_decided``.
- ``POST /handoff-requests {project_id, work_item_id, to_user_id, body}`` — admin/owner; ``{message, takeover}``:
  the request is also a pending takeover addressed to that person.
- ``POST /messages/{id}/redact`` — admin/owner; ``{message}`` (the tombstone).
- ``GET /action-needed`` — ``{count, items, viewer}`` across the caller's Workspaces; syncs notifications.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_board.takeover_listing import takeover_views

from ...db import get_db
from ...models import AgentBoardMessage, User, WorkItem
from ...schemas.core.workspace_ref import WorkspaceId
from ...services.access_control import _user_is_admin
from ...services.agent_board.action_needed import (
    action_needed,
    resolve_message_notifications,
    sync_notifications,
)
from ...services.agent_board.envelope import RECIPIENT_USER, envelopes
from ...services.agent_board.messages import AUTHOR_HUMAN, Author, decide, redact
from ...services.agent_board.reading import MAX_LIMIT, read_page, thread_of
from ...services.agent_board.takeovers import request_takeover
from ...services.auth import get_current_user
from .agent_board_access import require_member, viewer

router = APIRouter()

class DecisionBody(BaseModel):
    option: str | None = None
    text: str | None = None


class HandoffRequestBody(BaseModel):
    project_id: WorkspaceId
    work_item_id: str
    to_user_id: str
    body: str


async def _envelopes(db: AsyncSession, rows: list[AgentBoardMessage], user: User) -> list[dict[str, Any]]:
    return await envelopes(db, rows, viewer_kind=RECIPIENT_USER, viewer_ref=user.id, include_acks=True)


async def _message(db: AsyncSession, message_id: str, user: User, *, admin: bool = False):
    message = await db.get(AgentBoardMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    role = await require_member(db, user.id, message.project_id, admin=admin, not_found="Message not found")
    return message, role


@router.get("/messages")
async def list_messages(
    project_id: str = Query(..., min_length=1, max_length=64),
    cursor: str | None = Query(None, max_length=64),
    work_item_id: str | None = Query(None, max_length=64),
    kind: str | None = Query(None, max_length=40),
    agent_hash: str | None = Query(None, max_length=24),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    role = await require_member(db, current_user.id, project_id)
    rows, next_cursor = await read_page(db, project_ids=[project_id], cursor=cursor, work_item_id=work_item_id,
                                        kind=kind, agent_hash=agent_hash, limit=limit)
    return {"items": await _envelopes(db, rows, current_user), "next_cursor": next_cursor,
            "viewer": viewer(current_user.id, role)}


@router.get("/messages/{message_id}/thread")
async def message_thread(
    message_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    message, role = await _message(db, message_id, current_user)
    root, replies = await thread_of(db, message)
    rendered = await _envelopes(db, [root, *replies], current_user)
    return {"root": rendered[0], "replies": rendered[1:], "viewer": viewer(current_user.id, role)}


@router.post("/messages/{message_id}/decision")
async def decide_request(
    message_id: str,
    payload: DecisionBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    request, _ = await _message(db, message_id, current_user)
    decision = await decide(db, request=request, user_id=current_user.id, option=payload.option, text=payload.text)
    await resolve_message_notifications(db, request)
    [rendered] = await _envelopes(db, [decision], current_user)
    await db.commit()
    return {"decision": rendered}


@router.post("/handoff-requests")
async def request_handoff(
    payload: HandoffRequestBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Like every board route: an unknown and a foreign Workspace answer the same 404, so an outsider never learns
    # whether a Workspace exists; a member without the admin role gets 403.
    await require_member(db, current_user.id, payload.project_id, admin=True)
    item = await db.get(WorkItem, payload.work_item_id)
    if item is None or item.project_id != payload.project_id:
        raise HTTPException(status_code=404, detail="Work item not found")
    if not payload.body.strip():
        raise HTTPException(status_code=422, detail="body is required")
    # The request is also a pending takeover addressed to the chosen person, who confirms it in the UI.
    takeover = await request_takeover(
        db, item=item, to_user_id=payload.to_user_id, to_agent_hash=None, to_agent_kind=None, reason=payload.body,
        author=Author(AUTHOR_HUMAN, current_user.id), message_to_user_id=payload.to_user_id, require_claim=False,
    )
    message = await db.get(AgentBoardMessage, takeover.message_id)
    [rendered] = await _envelopes(db, [message], current_user)
    [view] = await takeover_views(db, [takeover])
    await db.commit()
    return {"message": rendered, "takeover": view}


@router.post("/messages/{message_id}/redact")
async def redact_message(
    message_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    message, _ = await _message(db, message_id, current_user, admin=True)
    await redact(db, message=message, actor_user_id=current_user.id)
    await resolve_message_notifications(db, message)
    [rendered] = await _envelopes(db, [message], current_user)
    await db.commit()
    return {"message": rendered}


@router.get("/action-needed")
async def list_action_needed(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items = await action_needed(db, current_user.id)
    await sync_notifications(db, current_user.id, items)
    await db.commit()
    platform_admin = await _user_is_admin(db, current_user.id)
    return {"count": len(items), "items": items,
            "viewer": {"user_id": current_user.id, "can_admin": platform_admin}}


__all__ = ["router"]
