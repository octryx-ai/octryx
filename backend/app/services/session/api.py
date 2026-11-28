"""Session API-oriented service helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import AuthenticationError

from ...models import Message, Session
from ...schemas.operations.session import MessageResponse, SessionResponse, SessionStreamTokenResponse
from ...time_utils import utc_isoformat
from ..agent_mode import resolve_agent_mode
from ..auth import create_session_stream_token, decode_session_stream_token
from ..data_access import bind_request_viewer
from .collaboration import get_session_access_role, list_accessible_sessions, require_session_access
from .resource_access import require_session_resource_access
from .turn_stop import stop_session_turn


def _build_session_response(
    session: Session,
    *,
    message_count: int,
    access_role: str | None = None,
) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        project_id=session.project_id,
        agent_type=session.agent_type,
        status=session.status,
        started_at=utc_isoformat(session.started_at) or "",
        ended_at=utc_isoformat(session.ended_at),
        message_count=message_count,
        access_role=access_role or "owner",
    )


def _build_message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        tool_calls=message.tool_calls,
        tool_results=message.tool_results,
        model=message.model,
        tokens_in=message.tokens_in,
        tokens_out=message.tokens_out,
        cost=float(message.cost) if message.cost else 0,
        created_at=utc_isoformat(message.created_at) or "",
    )


@dataclass(frozen=True, slots=True)
class SessionStreamAccessDecision:
    allowed: bool
    reason: str
    error_code: str
    user_id: str | None = None
    token_session_id: str | None = None
    access_role: str | None = None


async def list_session_responses(
    *, db: AsyncSession, user_id: str, project_id: str | None = None
) -> list[SessionResponse]:
    accessible_sessions = await list_accessible_sessions(db, user_id=user_id, project_id=project_id)
    session_ids = [session.id for session, _ in accessible_sessions]
    message_counts = await _count_session_messages_by_session_ids(db, session_ids=session_ids)

    responses: list[SessionResponse] = []
    for session, access_role in accessible_sessions:
        responses.append(
            _build_session_response(
                session,
                message_count=message_counts.get(session.id, 0),
                access_role=access_role,
            )
        )
    return responses


async def get_session_response(*, db: AsyncSession, session_id: str, user_id: str) -> SessionResponse:
    session, access_role = await require_session_access(db, session_id=session_id, user_id=user_id)
    message_count = await _count_session_messages(db, session_id=session.id)
    return _build_session_response(
        session,
        message_count=message_count,
        access_role=access_role,
    )


async def get_session_messages_response(*, db: AsyncSession, session_id: str, user_id: str) -> list[MessageResponse]:
    await require_session_access(db, session_id=session_id, user_id=user_id)
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    return [_build_message_response(message) for message in messages]


async def create_session_response(
    *,
    db: AsyncSession,
    user_id: str,
    project_id: str | None,
    agent_type: str | None,
) -> SessionResponse:
    from ..access_control import require_project_access

    # A named Workspace is resolved (it exists, and the caller has a role in it) before the session is written; a
    # blank one is absent already (``SessionCreate``: ``OptionalWorkspaceId``).
    await require_project_access(db, user_id, project_id)
    resolved_mode = await resolve_agent_mode(db, agent_type)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=project_id,
        agent_type=resolved_mode.key,
        status="active",
        origin="chat",
    )
    db.add(session)
    await db.commit()
    return _build_session_response(session, message_count=0)


async def create_stream_token_response(
    *,
    db: AsyncSession,
    session_id: str,
    user_id: str,
) -> SessionStreamTokenResponse:
    await require_session_access(db, session_id=session_id, user_id=user_id)
    return SessionStreamTokenResponse(
        session_id=session_id,
        token=create_session_stream_token(user_id=user_id, session_id=session_id),
    )


async def stop_session_turn_response(*, db: AsyncSession, session_id: str, user_id: str) -> SessionResponse:
    session = await require_session_resource_access(db, session_id=session_id, user_id=user_id, require_write=True)
    if str(session.status or "").strip().lower() == "running":
        await stop_session_turn(db, session)
    access_role = await get_session_access_role(db, session_id=session.id, user_id=user_id)
    message_count = await _count_session_messages(db, session_id=session.id)
    return _build_session_response(session, message_count=message_count, access_role=access_role or "admin")


async def resolve_session_stream_access(
    *,
    db: AsyncSession,
    session_id: str,
    token: str,
) -> SessionStreamAccessDecision:
    if not token:
        return SessionStreamAccessDecision(
            allowed=False,
            reason="Session stream token required",
            error_code="stream_token_required",
        )

    try:
        user_id, token_session_id = decode_session_stream_token(token)
    except AuthenticationError as exc:
        return SessionStreamAccessDecision(
            allowed=False,
            reason=str(exc),
            error_code="stream_token_invalid",
        )
    if token_session_id != session_id:
        return SessionStreamAccessDecision(
            allowed=False,
            reason="Session stream token does not match requested session",
            error_code="stream_token_session_mismatch",
            user_id=user_id,
            token_session_id=token_session_id,
        )

    bind_request_viewer(user_id)
    access_role = await get_session_access_role(db, session_id=session_id, user_id=user_id)
    if access_role is None:
        return SessionStreamAccessDecision(
            allowed=False,
            reason="Session not found",
            error_code="stream_session_not_found",
            user_id=user_id,
            token_session_id=token_session_id,
        )

    return SessionStreamAccessDecision(
        allowed=True,
        reason="allowed",
        error_code="stream_allowed",
        user_id=user_id,
        token_session_id=token_session_id,
        access_role=access_role,
    )


async def _count_session_messages(db: AsyncSession, *, session_id: str) -> int:
    result = await db.execute(select(func.count(Message.id)).where(Message.session_id == session_id))
    return result.scalar() or 0


async def _count_session_messages_by_session_ids(db: AsyncSession, *, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}

    rows = await db.execute(
        select(Message.session_id, func.count(Message.id))
        .where(Message.session_id.in_(session_ids))
        .group_by(Message.session_id)
    )
    return {session_id: int(message_count or 0) for session_id, message_count in rows.all()}
