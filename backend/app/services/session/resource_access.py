"""Access to records that belong to a chat session, by the chat-session access rule."""

from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ..admin.governance.admin_access_service import is_global_admin
from .collaboration import require_session_access

SESSION_NOT_FOUND_DETAIL = "Session not found"


class SessionOwnedRecord(Protocol):
    session_id: str


async def require_session_resource_access(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    require_write: bool = False,
    not_found_detail: str = SESSION_NOT_FOUND_DETAIL,
) -> Session:
    if await is_global_admin(db, user_id):
        from ..project.private_workspace import refuse_foreign_private  # noqa: PLC0415

        session = await db.get(Session, str(session_id or ""))
        # Somebody else's private Workspace stays closed to platform admins: as if it did not exist.
        if session is None or (session.project_id and await refuse_foreign_private(db, session.project_id, user_id)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
        return session
    try:
        session, _role = await require_session_access(
            db, session_id=str(session_id or ""), user_id=user_id, require_write=require_write
        )
    except HTTPException as refused:
        if refused.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail) from None
        raise
    return session


async def require_record_access(
    db: AsyncSession,
    record: SessionOwnedRecord | None,
    *,
    user_id: str,
    not_found_detail: str,
    require_write: bool = False,
) -> Session:
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    return await require_session_resource_access(
        db,
        session_id=record.session_id,
        user_id=user_id,
        require_write=require_write,
        not_found_detail=not_found_detail,
    )


def require_matching_project(session: Session, project_id: str | None) -> str | None:
    # A record created for a session belongs to the session's Workspace, never to another one.
    if project_id is not None and project_id != session.project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id does not match the session")
    return session.project_id


__all__ = [
    "SESSION_NOT_FOUND_DETAIL",
    "require_matching_project",
    "require_record_access",
    "require_session_resource_access",
]
