"""GDPR export of one person's data as a zip of JSON files."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Message,
    MessageFeedback,
    Notification,
    Project,
    Session,
    TeamMember,
    User,
    UserProject,
    UserRole,
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


async def _build_user_data_gdpr_zip(db: AsyncSession, *, user_id: str, requester_id: str | None = None) -> bytes:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    sessions = await _gdpr_sessions(db, user_id=user_id, requester_id=requester_id)
    messages, feedbacks = await _gdpr_messages_and_feedback(db, [row.id for row in sessions])
    notifications = (await db.execute(select(Notification).where(Notification.user_id == user_id))).scalars().all()
    team_memberships = (await db.execute(select(TeamMember).where(TeamMember.user_id == user_id))).scalars().all()
    project_memberships = (await db.execute(select(UserProject).where(UserProject.user_id == user_id))).scalars().all()
    roles = (await db.execute(select(UserRole).where(UserRole.user_id == user_id))).scalars().all()

    memory = io.BytesIO()
    with zipfile.ZipFile(memory, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("user.json", json.dumps(_user_json(user), indent=2))
        archive.writestr("sessions.json", json.dumps([_session_json(row) for row in sessions], indent=2))
        archive.writestr("messages.json", json.dumps([_message_json(row) for row in messages], indent=2))
        archive.writestr("message_feedback.json", json.dumps([_feedback_json(row) for row in feedbacks], indent=2))
        archive.writestr(
            "notifications.json", json.dumps([_notification_json(row) for row in notifications], indent=2)
        )
        archive.writestr(
            "memberships.json",
            json.dumps(
                {
                    "team_memberships": [{"team_id": row.team_id, "role": row.role} for row in team_memberships],
                    "project_memberships": [
                        {"project_id": row.project_id, "role": row.role} for row in project_memberships
                    ],
                    "roles": [{"role_id": row.role_id} for row in roles],
                },
                indent=2,
            ),
        )
    return memory.getvalue()


async def _gdpr_sessions(db: AsyncSession, *, user_id: str, requester_id: str | None) -> list[Session]:
    query = select(Session).where(Session.user_id == user_id)
    if requester_id is not None and str(requester_id) != str(user_id):
        # An admin's export of another person leaves their private Workspace out; only the person's
        # own export contains it.
        from ..project.private_workspace import PRIVATE_ACCESS_MODE  # noqa: PLC0415

        query = query.where(or_(Session.project_id.is_(None), Session.project_id.not_in(
            select(Project.id).where(Project.access_mode == PRIVATE_ACCESS_MODE).scalar_subquery())))
    return (await db.execute(query.order_by(Session.started_at.asc()))).scalars().all()


async def _gdpr_messages_and_feedback(db: AsyncSession, session_ids: list[str]) -> tuple[list[Any], list[Any]]:
    messages = []
    feedbacks = []
    if session_ids:
        messages = (
            (
                await db.execute(
                    select(Message).where(Message.session_id.in_(session_ids)).order_by(Message.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        message_ids = [row.id for row in messages]
        if message_ids:
            feedbacks = (
                (
                    await db.execute(
                        select(MessageFeedback)
                        .where(MessageFeedback.message_id.in_(message_ids))
                        .order_by(MessageFeedback.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
    return messages, feedbacks


def _user_json(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "auth_source": user.auth_source,
        "created_at": _iso(user.created_at),
    }


def _session_json(row: Session) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "agent_type": row.agent_type,
        "status": row.status,
        "metadata": row.metadata_ or {},
        "started_at": _iso(row.started_at),
        "ended_at": _iso(row.ended_at),
    }


def _message_json(row: Message) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content or "",
        "tool_calls": row.tool_calls or [],
        "tool_results": row.tool_results or [],
        "model": row.model,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "cost": float(row.cost or 0),
        "created_at": _iso(row.created_at),
    }


def _feedback_json(row: MessageFeedback) -> dict[str, Any]:
    return {
        "id": row.id,
        "message_id": row.message_id,
        "user_id": row.user_id,
        "rating": row.rating,
        "comment": row.comment or "",
        "created_at": _iso(row.created_at),
    }


def _notification_json(row: Notification) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "is_read": row.is_read,
        "created_at": _iso(row.created_at),
    }
