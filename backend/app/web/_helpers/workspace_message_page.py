"""Query helpers for workspace-backed chat message pages."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, ToolCall, TurnTrace, User
from ...models import Session as AgentSession
from ...services.knowledge.memory.feedback_query import own_feedback_entries


@dataclass(slots=True)
class WorkspaceMessagePageBundle:
    messages: list[Message]
    tool_calls: list[ToolCall]
    turn_trace_rows: list[tuple[str | None, str, str | None, str | None]]
    feedbacks: list[dict]
    has_more: bool
    authors: dict[str, str] = field(default_factory=dict)  # user id -> the name a user message is shown under


async def _author_names(db: AsyncSession, messages: list[Message], owner_id: str | None) -> dict[str, str]:
    author_ids = {message.author_user_id or owner_id for message in messages if message.author_user_id or owner_id}
    if not author_ids:
        return {}
    rows = await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(author_ids)))
    return {str(user_id): str(display_name or username or "") for user_id, display_name, username in rows.all()}


async def load_workspace_message_page_bundle(
    db: AsyncSession,
    *,
    session: AgentSession,
    user: User,
    limit: int,
    before_message_id: str | None = None,
) -> WorkspaceMessagePageBundle:
    filters = [Message.session_id == session.id]
    if before_message_id:
        boundary = (
            await db.execute(
                select(Message.id, Message.created_at).where(
                    Message.id == before_message_id,
                    Message.session_id == session.id,
                )
            )
        ).one_or_none()
        if boundary is None:
            return WorkspaceMessagePageBundle(messages=[], tool_calls=[], turn_trace_rows=[], feedbacks=[],
                                              has_more=False)
        boundary_id, boundary_created_at = boundary
        filters.append(
            or_(
                Message.created_at < boundary_created_at,
                and_(Message.created_at == boundary_created_at, Message.id < boundary_id),
            )
        )

    message_models = (
        (
            await db.execute(
                select(Message).where(*filters).order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(message_models) > limit
    if has_more:
        message_models = message_models[:limit]
    message_models = list(reversed(message_models))
    message_ids = [message.id for message in message_models]

    tool_calls = (
        (
            await db.execute(
                select(ToolCall)
                .where(
                    ToolCall.session_id == session.id,
                    ToolCall.message_id.in_(message_ids),
                )
                .order_by(ToolCall.created_at.asc(), ToolCall.id.asc())
            )
        )
        .scalars()
        .all()
        if message_ids
        else []
    )
    turn_trace_rows = (
        (
            await db.execute(
                select(
                    TurnTrace.message_id,
                    TurnTrace.id,
                    TurnTrace.provider,
                    TurnTrace.model,
                )
                .where(
                    TurnTrace.session_id == session.id,
                    TurnTrace.message_id.in_(message_ids),
                )
                .order_by(TurnTrace.created_at.asc())
            )
        ).all()
        if message_ids
        else []
    )
    # The viewer's own answer feedback, from the Memory lobe (``knowledge_answer_feedback``).
    feedbacks = await own_feedback_entries(db, user_id=str(user.id), message_ids=message_ids)
    authors = await _author_names(db, message_models, session.user_id)

    return WorkspaceMessagePageBundle(
        messages=message_models,
        tool_calls=tool_calls,
        turn_trace_rows=turn_trace_rows,
        feedbacks=feedbacks,
        has_more=has_more,
        authors=authors,
    )
