"""Session access control for team vs user project modes.

Team projects: all team members see all sessions via UserProject membership.
User projects: each user only sees their own sessions unless explicitly shared.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project, Session, SessionAccess, UserProject


async def session_visible_to_user(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    user_roles: list[str],
    include_private: bool = False,
) -> bool:
    """Check if a session is visible to a given user.

    Team project: all team members see all sessions.
    User project: only the session owner sees it, unless explicit grant exists.
    Private sessions: never visible via project membership (requires explicit grant).
    """
    session = await db.get(Session, session_id)
    if session is None:
        return False

    if session.metadata_.get("private", False) and not include_private:
        return await _has_explicit_access_grant(db, session_id=session_id, user_id=user_id)

    if session.project_id is None:
        return session.user_id == user_id

    project = await db.get(Project, session.project_id)
    if project is None:
        return session.user_id == user_id

    if project.access_mode == "team":
        return await _is_team_member(db, project_id=project.id, user_id=user_id)

    if project.access_mode == "user":
        if session.user_id == user_id:
            return True
        return await _has_explicit_access_grant(db, session_id=session_id, user_id=user_id)

    return session.user_id == user_id


async def _is_team_member(db: AsyncSession, *, project_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(UserProject).where(
            and_(UserProject.project_id == project_id, UserProject.user_id == user_id)
        )
    )
    return result.scalar_one_or_none() is not None


async def _has_explicit_access_grant(db: AsyncSession, *, session_id: str, user_id: str) -> bool:
    now = datetime.utcnow()
    result = await db.execute(
        select(SessionAccess).where(
            and_(
                SessionAccess.session_id == session_id,
                SessionAccess.user_id == user_id,
                SessionAccess.expires_at.is_(None) | (SessionAccess.expires_at > now),
            )
        )
    )
    return result.scalar_one_or_none() is not None


async def grant_session_access(
    db: AsyncSession,
    *,
    session_id: str,
    target_user_id: str,
    scope: str = "read",
    granted_by: str | None = None,
    expires_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> SessionAccess:
    """Grant a user explicit access to a session."""
    existing = await db.execute(
        select(SessionAccess).where(
            and_(
                SessionAccess.session_id == session_id,
                SessionAccess.user_id == target_user_id,
            )
        )
    )
    grant = existing.scalar_one_or_none()
    if grant is None:
        grant = SessionAccess(
            id=str(uuid.uuid4()),
            session_id=session_id,
            user_id=target_user_id,
            access_scope=scope,
            granted_by=granted_by,
            granted_at=datetime.utcnow(),
            expires_at=expires_at,
            metadata_=metadata or {},
        )
        db.add(grant)
    else:
        grant.access_scope = scope
        grant.granted_by = granted_by
        grant.expires_at = expires_at
        if metadata:
            grant.metadata_ = metadata
        grant.updated_at = datetime.utcnow()
    await db.commit()
    return grant


async def revoke_session_access(
    db: AsyncSession,
    *,
    session_id: str,
    target_user_id: str,
) -> bool:
    """Revoke a user's explicit access to a session."""
    result = await db.execute(
        select(SessionAccess).where(
            and_(
                SessionAccess.session_id == session_id,
                SessionAccess.user_id == target_user_id,
            )
        )
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        return False
    await db.delete(grant)
    await db.commit()
    return True


#: Session roles that may grant or revoke explicit access to others.
GRANT_AUTHORITY_ROLES = frozenset({"owner", "admin"})


async def require_grant_authority(db: AsyncSession, *, session_id: str, user_id: str) -> None:
    """Only the session owner, an ``admin`` grant holder or a global admin changes access grants.

    404 when the caller cannot see the session at all (the same answer as an unknown id), 403
    when they can see it but hold a lower role.
    """
    from fastapi import HTTPException

    from .admin.governance.admin_access_service import is_global_admin
    from .session.collaboration import get_session_access_role

    if await is_global_admin(db, user_id):
        from .project.private_workspace import refuse_foreign_private_session

        if await db.get(Session, session_id) is None or await refuse_foreign_private_session(db, session_id, user_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return
    role = await get_session_access_role(db, session_id=session_id, user_id=user_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if role not in GRANT_AUTHORITY_ROLES:
        raise HTTPException(status_code=403, detail="Session owner or admin access required")

