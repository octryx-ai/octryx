"""``/api/v1/workspaces/{id}/work/me``: the person's own "You in Jira" choice for "My work" (members only).

GET reads it, PUT ``{source_type: "jira", account_id}`` chooses an assignee of the Workspace's Jira items (422
otherwise), DELETE clears it. Only for oneself; the choice is the person's linked Jira account.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import require_visible_workspace
from ...services.auth import get_current_user
from ...services.linked_accounts.contract import LinkedAccountError
from ...services.linked_accounts.work_me import SOURCE_TYPE, choose_me, clear_me, read_me

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/work/me", tags=["work"])


class Choice(BaseModel):
    source_type: str = Field(default=SOURCE_TYPE, max_length=20)
    account_id: str = Field(min_length=1, max_length=220)


async def _member(db: AsyncSession, user: User, workspace_id: str) -> None:
    """A Workspace that does not exist or that the caller is no member of answers the same 404 (platform admins:
    every existing Workspace)."""
    await require_visible_workspace(db, user.id, workspace_id)


def _refused(error: LinkedAccountError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


@router.get("")
async def get_me(workspace_id: str, current_user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    await _member(db, current_user, workspace_id)
    return await read_me(db, current_user, workspace_id)


@router.put("")
async def put_me(workspace_id: str, body: Choice, current_user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    await _member(db, current_user, workspace_id)
    if body.source_type != SOURCE_TYPE:
        raise HTTPException(status_code=422, detail={"code": "unsupported_source", "message": "Only jira."})
    try:
        view = await choose_me(db, current_user, workspace_id, body.account_id)
    except LinkedAccountError as error:
        await db.rollback()
        raise _refused(error) from error
    await db.commit()
    return view


@router.delete("")
async def delete_me(workspace_id: str, current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    await _member(db, current_user, workspace_id)
    try:
        view = await clear_me(db, current_user, workspace_id)
    except LinkedAccountError as error:
        raise _refused(error) from error
    await db.commit()
    return view
