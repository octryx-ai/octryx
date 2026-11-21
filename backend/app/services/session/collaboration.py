from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, Session, SessionCollaborator, SessionHandover, User, UserProject
from ...time_utils import utc_now
from ..team_notification import create_notification

COLLABORATOR_ROLES = {"observer", "contributor"}
HANDOVER_STATUSES = {"pending", "accepted", "declined"}


async def get_session_access_role(db: AsyncSession, *, session_id: str, user_id: str) -> str | None:
    session = await db.get(Session, session_id)
    if session is None:
        return None
    if session.user_id == user_id:
        return "owner"
    collaborator = await db.get(SessionCollaborator, {"session_id": session_id, "user_id": user_id})
    if collaborator is not None:
        return str(collaborator.role or "observer")
    if session.project_id and session.project_id in await _get_team_accessible_project_ids(db, user_id):
        return "team_member"
    grant_role = await _session_access_grant_role(db, session_id, user_id)
    if grant_role:
        return grant_role
    return None


async def _get_team_accessible_project_ids(db: AsyncSession, user_id: str) -> set[str]:
    rows = (
        (
            await db.execute(
                select(Project.id).where(
                    Project.access_mode == "team",
                    Project.id.in_(select(UserProject.project_id).where(UserProject.user_id == user_id)),
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def require_session_access(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    require_write: bool = False,
) -> tuple[Session, str]:
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id == user_id:
        return session, "owner"
    collaborator = await db.get(SessionCollaborator, {"session_id": session_id, "user_id": user_id})
    if collaborator is not None:
        role = str(collaborator.role or "observer")
        if require_write and role not in {"contributor"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Contributor access required")
        return session, role
    if session.project_id:
        team_project_ids = await _get_team_accessible_project_ids(db, user_id)
        if session.project_id in team_project_ids:
            return session, "team_member"
    grant_role = await _session_access_grant_role(db, session_id, user_id)
    if grant_role:
        if require_write and grant_role not in {"read_write", "admin"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Write access required")
        return session, grant_role
    raise HTTPException(status_code=404, detail="Session not found")


def serialize_collaborator(row: SessionCollaborator) -> dict:
    return {
        "session_id": row.session_id,
        "user_id": row.user_id,
        "role": row.role,
        "invited_by": row.invited_by,
        "joined_at": row.joined_at.isoformat() if row.joined_at else None,
    }


def serialize_handover(row: SessionHandover) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "from_user_id": row.from_user_id,
        "to_user_id": row.to_user_id,
        "reason": row.reason,
        "context_summary": row.context_summary,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


async def list_accessible_sessions(db: AsyncSession, *, user_id: str) -> list[tuple[Session, str]]:
    owned = (
        (
            await db.execute(
                select(Session).where(Session.user_id == user_id).order_by(Session.started_at.desc()).limit(50)
            )
        )
        .scalars()
        .all()
    )
    collaborator_rows = (
        await db.execute(
            select(SessionCollaborator, Session)
            .join(Session, Session.id == SessionCollaborator.session_id)
            .where(SessionCollaborator.user_id == user_id)
            .order_by(Session.started_at.desc())
            .limit(50)
        )
    ).all()

    team_project_ids: set[str] = set()
    user_project_ids: set[str] = set()
    if owned or collaborator_rows:
        all_project_ids = {s.project_id for s in list(owned) + [s for _, s in collaborator_rows] if s.project_id}
        if all_project_ids:
            rows = (
                await db.execute(select(Project.id, Project.access_mode).where(Project.id.in_(all_project_ids)))
            ).all()
            for pid, mode in rows:
                if mode == "team":
                    team_project_ids.add(pid)
                else:
                    user_project_ids.add(pid)

    seen: set[str] = set()
    result: list[tuple[Session, str]] = []
    for session in owned:
        if session.id in seen:
            continue
        access_role = "owner"
        if session.project_id and session.project_id in user_project_ids and session.user_id != user_id:
            access_role = await _session_access_grant_role(db, session.id, user_id)
        seen.add(session.id)
        result.append((session, access_role))
    for collaborator, session in collaborator_rows:
        if session.id in seen:
            continue
        access_role = str(collaborator.role or "observer")
        seen.add(session.id)
        result.append((session, access_role))
    result.sort(key=lambda item: item[0].started_at, reverse=True)
    return result[:50]


async def _session_access_grant_role(db: AsyncSession, session_id: str, user_id: str) -> str:
    from datetime import datetime

    from ...models import SessionAccess

    now = datetime.utcnow()
    grant = (
        await db.execute(
            select(SessionAccess).where(
                SessionAccess.session_id == session_id,
                SessionAccess.user_id == user_id,
                (SessionAccess.expires_at.is_(None)) | (SessionAccess.expires_at > now),
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        return ""
    return str(grant.access_scope or "read")


async def list_session_collaborators(db: AsyncSession, *, session_id: str, current_user: User) -> list[dict]:
    await require_session_access(db, session_id=session_id, user_id=current_user.id)
    rows = (
        (
            await db.execute(
                select(SessionCollaborator)
                .where(SessionCollaborator.session_id == session_id)
                .order_by(SessionCollaborator.joined_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_collaborator(row) for row in rows]


async def add_session_collaborator(
    db: AsyncSession,
    *,
    session_id: str,
    current_user: User,
    target_user_id: str,
    role: str,
) -> dict:
    session, access_role = await require_session_access(
        db,
        session_id=session_id,
        user_id=current_user.id,
        require_write=True,
    )
    if access_role not in {"owner", "contributor"}:
        raise HTTPException(status_code=403, detail="Contributor access required")
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in COLLABORATOR_ROLES:
        raise HTTPException(status_code=400, detail="Invalid collaborator role")
    if target_user_id == session.user_id:
        raise HTTPException(status_code=400, detail="Session owner is already primary")
    target_user = await db.get(User, target_user_id)
    if target_user is None or not target_user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    row = await db.get(SessionCollaborator, {"session_id": session_id, "user_id": target_user_id})
    if row is None:
        row = SessionCollaborator(
            session_id=session_id,
            user_id=target_user_id,
            role=normalized_role,
            invited_by=current_user.id,
        )
        db.add(row)
    else:
        row.role = normalized_role
        row.invited_by = current_user.id
        row.joined_at = utc_now()
    await create_notification(
        db,
        user_id=target_user_id,
        notification_type="session.collaborator_invited",
        title="Session shared with you",
        body=f"You were added as {normalized_role} to a live session.",
        link=f"/chat?session_id={session_id}",
        project_id=session.project_id,
        payload={"session_id": session_id, "role": normalized_role},
    )
    await db.commit()
    return serialize_collaborator(row)


async def create_session_handover(
    db: AsyncSession,
    *,
    session_id: str,
    current_user: User,
    to_user_id: str,
    reason: str | None,
    context_summary: str | None,
) -> dict:
    session, _ = await require_session_access(db, session_id=session_id, user_id=current_user.id, require_write=True)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the session owner can hand over a session")
    if to_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot hand over to yourself")
    target_user = await db.get(User, to_user_id)
    if target_user is None or not target_user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    row = SessionHandover(
        id=str(uuid.uuid4()),
        session_id=session_id,
        from_user_id=current_user.id,
        to_user_id=to_user_id,
        reason=(reason or "").strip() or None,
        context_summary=(context_summary or "").strip() or None,
        status="pending",
    )
    db.add(row)
    await create_notification(
        db,
        user_id=to_user_id,
        notification_type="session.handover_requested",
        title="Session handover requested",
        body=(reason or "A session was handed over to you.").strip(),
        link=f"/chat?session_id={session_id}",
        project_id=session.project_id,
        payload={"session_id": session_id, "handover_id": row.id},
    )
    await db.commit()
    return serialize_handover(row)


async def list_session_handovers(
    db: AsyncSession,
    *,
    current_user: User,
    status_filter: str | None = None,
) -> list[dict]:
    stmt = select(SessionHandover).where(
        or_(SessionHandover.from_user_id == current_user.id, SessionHandover.to_user_id == current_user.id)
    )
    if status_filter:
        stmt = stmt.where(SessionHandover.status == status_filter)
    rows = (await db.execute(stmt.order_by(SessionHandover.created_at.desc()))).scalars().all()
    return [serialize_handover(row) for row in rows]


async def respond_to_session_handover(
    db: AsyncSession,
    *,
    handover_id: str,
    current_user: User,
    action: str,
) -> dict:
    row = await db.get(SessionHandover, handover_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Handover not found")
    if row.to_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the handover target can respond")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="Handover already resolved")
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"accept", "decline"}:
        raise HTTPException(status_code=400, detail="Invalid handover action")
    session = await db.get(Session, row.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if normalized_action == "accept":
        previous_owner_id = session.user_id
        session.user_id = current_user.id
        collaborator = await db.get(SessionCollaborator, {"session_id": session.id, "user_id": previous_owner_id})
        if collaborator is None:
            db.add(
                SessionCollaborator(
                    session_id=session.id,
                    user_id=previous_owner_id,
                    role="contributor",
                    invited_by=current_user.id,
                )
            )
        else:
            collaborator.role = "contributor"
            collaborator.invited_by = current_user.id
            collaborator.joined_at = utc_now()
        target_collaborator = await db.get(SessionCollaborator, {"session_id": session.id, "user_id": current_user.id})
        if target_collaborator is not None:
            await db.delete(target_collaborator)
        row.status = "accepted"
        title = "Session handover accepted"
        body = "Your session was accepted by the new owner."
    else:
        row.status = "declined"
        title = "Session handover declined"
        body = "Your session handover request was declined."
    row.resolved_at = utc_now()
    await create_notification(
        db,
        user_id=row.from_user_id,
        notification_type=f"session.handover_{row.status}",
        title=title,
        body=body,
        link=f"/chat?session_id={row.session_id}",
        project_id=session.project_id,
        payload={"session_id": row.session_id, "handover_id": row.id, "status": row.status},
    )
    await db.commit()
    return serialize_handover(row)
