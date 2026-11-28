"""Session handovers: to a named person or into the Workspace's session pool; a run moves with its thread."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.session.handover_pool import pool_entries
from ....services.session.handovers import HandoverError, decline, hand_over, my_handovers, serialize_handover, take

router = APIRouter(prefix="/api/v1/session-handovers", tags=["session-handovers"])


class HandoverCreate(BaseModel):
    session_id: str | None = Field(default=None, max_length=36)
    run_id: str | None = Field(default=None, max_length=36)
    to_user_id: str | None = Field(default=None, max_length=36)
    reason: str | None = Field(default=None, max_length=500)
    context_summary: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _one_subject(self) -> HandoverCreate:
        if bool(self.session_id) == bool(self.run_id):
            raise ValueError("Name the session or the run.")
        return self


class TakeBody(BaseModel):
    runtime_target: dict[str, Any] | None = None


class DeclineBody(BaseModel):
    reason: str = Field(default="", max_length=500)


def _refused(error: HandoverError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error)})


@router.post("")
async def post_handover(body: HandoverCreate, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    try:
        row = await hand_over(db, user=current_user, session_id=body.session_id, run_id=body.run_id,
                              to_user_id=body.to_user_id, reason=body.reason, context_summary=body.context_summary)
    except HandoverError as error:
        raise _refused(error) from error
    await db.commit()
    return {"handover": serialize_handover(row)}


@router.get("")
async def get_handovers(status: str | None = None, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    return {"handovers": await my_handovers(db, current_user, status=(status or "").strip() or None)}


@router.get("/pool")
async def get_pool(workspace_id: str | None = None, current_user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    return {"entries": await pool_entries(db, current_user, workspace_id=workspace_id or None)}


@router.post("/{handover_id}/accept")
async def post_accept(handover_id: str, body: TakeBody | None = None, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    try:
        taken = await take(db, handover_id, user=current_user,
                           runtime_target=body.runtime_target if body is not None else None)
    except HandoverError as error:
        raise _refused(error) from error
    await db.commit()
    return taken


@router.post("/{handover_id}/decline")
async def post_decline(handover_id: str, body: DeclineBody | None = None,
                       current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        row = await decline(db, handover_id, user=current_user, reason=body.reason if body is not None else "")
    except HandoverError as error:
        raise _refused(error) from error
    await db.commit()
    return {"handover": serialize_handover(row)}
