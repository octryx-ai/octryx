"""Explicit session access grants: grant, revoke, and who may grant."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, SessionAccess


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
    # 404 when the caller cannot see the session, like an unknown id; 403 for a lower role.
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
