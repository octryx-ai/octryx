"""User control over the Memory lobe of one Workspace."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....models.project.knowledge_memory import MAX_MEMORY_TEXT_CHARS
from ....services.admin.governance.admin_access_service import is_global_admin
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    authorize_workspace,
)
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.memory.control import (
    confirm_memory,
    correct_memory,
    forget_memory,
    list_memory,
    reject_memory,
)
from ....services.knowledge.memory.errors import MemoryRefusedError
from ....services.knowledge.memory.settings import (
    CONFIRM_ROLE_CHOICES,
    CONFIRM_ROLES,
    SESSION_LESSONS,
    automatic_capture_enabled,
    confirm_roles,
    session_lessons_enabled,
    set_automatic_capture,
    set_memory_policy,
)
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/memory", tags=["workspace-knowledge"])

STATUS_BY_REASON = {
    "not_found": 404,
    "author_required": 403,
    "secret_detected": 422,
    "invalid_text": 422,
    "invalid_request": 422,
    "not_active": 409,
}


class CorrectionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_MEMORY_TEXT_CHARS)


class MemorySettingsRequest(BaseModel):
    automatic_capture: bool | None = None
    # Lessons learned from octryx sessions, and who may confirm them.
    session_lessons: bool | None = None
    confirm_roles: list[str] | None = None


async def _authorized(db, user: User, workspace_id: str) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


def _refused(error: MemoryRefusedError) -> HTTPException:
    return HTTPException(status_code=STATUS_BY_REASON.get(error.reason, 422), detail=error.message)


async def _overview(db, authorized: AuthorizedWorkspace, user: User, *, include_history: bool = False) -> dict:
    return {
        "workspace_id": authorized.project_id,
        "may_author": authorized.may_author,
        "automatic_capture": await automatic_capture_enabled(db, authorized.project_id),
        "session_lessons": await session_lessons_enabled(db, authorized.project_id),
        "confirm_roles": list(await confirm_roles(db, authorized.project_id)),
        "items": await list_memory(db, authorized=authorized, user_id=str(user.id), include_history=include_history),
    }


@router.get("")
async def list_workspace_memory(
    workspace_id: str,
    include_history: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    return await _overview(db, authorized, current_user, include_history=include_history)


@router.post("/{memory_id}/confirm")
async def confirm_workspace_memory(
    workspace_id: str,
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    try:
        await confirm_memory(db, authorized=authorized, user_id=str(current_user.id), memory_id=memory_id)
    except MemoryRefusedError as error:
        raise _refused(error) from None
    await db.commit()
    return await _overview(db, authorized, current_user)


@router.post("/{memory_id}/reject")
async def reject_workspace_memory(
    workspace_id: str,
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a session's proposed lesson: it is deleted and the rejection is audited."""
    authorized = await _authorized(db, current_user, workspace_id)
    try:
        await reject_memory(db, authorized=authorized, user_id=str(current_user.id), memory_id=memory_id)
    except MemoryRefusedError as error:
        raise _refused(error) from None
    await db.commit()
    return await _overview(db, authorized, current_user)


@router.post("/{memory_id}/correct")
async def correct_workspace_memory(
    workspace_id: str,
    memory_id: str,
    body: CorrectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace a memory with the corrected statement; the old item becomes superseded."""
    authorized = await _authorized(db, current_user, workspace_id)
    try:
        await correct_memory(
            db, authorized=authorized, user_id=str(current_user.id), memory_id=memory_id, text=body.text
        )
    except MemoryRefusedError as error:
        raise _refused(error) from None
    await db.commit()
    return await _overview(db, authorized, current_user)


@router.post("/{memory_id}/forget")
async def forget_workspace_memory(
    workspace_id: str,
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Erase the memory's text (and its older versions'); only a tombstone remains."""
    authorized = await _authorized(db, current_user, workspace_id)
    try:
        await forget_memory(db, authorized=authorized, user_id=str(current_user.id), memory_id=memory_id)
    except MemoryRefusedError as error:
        raise _refused(error) from None
    await db.commit()
    return await _overview(db, authorized, current_user)


@router.put("/settings")
async def set_workspace_memory_settings(
    workspace_id: str,
    body: MemorySettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Automatic capture at turn end: off by default, switched per Workspace by an admin or owner."""
    authorized = await _authorized(db, current_user, workspace_id)
    if not authorized.may_author:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL)
    if body.automatic_capture is not None:
        await set_automatic_capture(db, authorized.project_id, enabled=body.automatic_capture)
    values: dict = {}
    if body.session_lessons is not None:
        values[SESSION_LESSONS] = body.session_lessons
    if body.confirm_roles is not None:
        if any(role not in CONFIRM_ROLE_CHOICES for role in body.confirm_roles):
            raise HTTPException(status_code=422, detail="confirm_roles_invalid")
        current = set(await confirm_roles(db, authorized.project_id))
        if not await is_global_admin(db, str(current_user.id)) and not set(body.confirm_roles) <= current:
            # A Workspace owner may narrow who confirms; widening it is a platform admin's decision.
            raise HTTPException(status_code=403, detail="only a platform admin can widen who confirms lessons")
        values[CONFIRM_ROLES] = [role for role in CONFIRM_ROLE_CHOICES if role in body.confirm_roles]
    if values:
        await set_memory_policy(db, authorized.project_id, **values)
    await db.commit()
    return await _overview(db, authorized, current_user)
