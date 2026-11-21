"""Which user message a chat rerun starts from, for a message, tool call, approval or change preview."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ChangePreview, Message, Session, ToolCall


async def resolve_chat_rerun_target_message(
    db: AsyncSession,
    *,
    session: Session,
    message: Message,
) -> Message:
    if str(message.session_id or "") != str(session.id or ""):
        raise ValueError("Target message does not belong to the selected session")
    role = str(message.role or "").strip()
    if role == "user":
        return message
    if role != "assistant":
        raise ValueError("Only user or assistant messages can be retried from this point")

    ordered_messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )
        .scalars()
        .all()
    )
    assistant_index = next((index for index, row in enumerate(ordered_messages) if row.id == message.id), -1)
    if assistant_index < 0:
        raise ValueError("Target message is not part of the selected session")
    for index in range(assistant_index - 1, -1, -1):
        candidate = ordered_messages[index]
        if str(candidate.role or "").strip() == "user":
            return candidate
    raise ValueError("No preceding user message exists for this assistant response")


async def resolve_chat_rerun_target_message_for_tool_call(
    db: AsyncSession,
    *,
    session: Session,
    tool_call: ToolCall,
) -> Message:
    if str(tool_call.session_id or "") != str(session.id or ""):
        raise ValueError("Target tool call does not belong to the selected session")
    message_id = str(tool_call.message_id or "").strip()
    if not message_id:
        raise ValueError("This tool call cannot be retried because it is not linked to a message")
    message = (
        await db.execute(select(Message).where(Message.id == message_id, Message.session_id == session.id))
    ).scalar_one_or_none()
    if message is None:
        raise ValueError("The parent message for this tool call no longer exists")
    return await resolve_chat_rerun_target_message(
        db,
        session=session,
        message=message,
    )


async def resolve_chat_rerun_target_message_for_approval(
    db: AsyncSession,
    *,
    session: Session,
    approval: Approval,
) -> Message:
    if str(approval.session_id or "") != str(session.id or ""):
        raise ValueError("Target approval does not belong to the selected session")
    cutoff = approval.created_at
    ordered_messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )
        .scalars()
        .all()
    )
    fallback_user: Message | None = None
    for message in reversed(ordered_messages):
        if cutoff and message.created_at and message.created_at > cutoff:
            continue
        role = str(message.role or "").strip()
        if role == "assistant":
            return await resolve_chat_rerun_target_message(
                db,
                session=session,
                message=message,
            )
        if role == "user" and fallback_user is None:
            fallback_user = message
    if fallback_user is not None:
        return fallback_user
    raise ValueError("No preceding user message exists for this approval")


async def resolve_chat_rerun_target_message_for_change_preview(
    db: AsyncSession,
    *,
    session: Session,
    change_preview: ChangePreview,
) -> Message:
    if str(change_preview.session_id or "") != str(session.id or ""):
        raise ValueError("Target change preview does not belong to the selected session")
    if str(change_preview.approval_id or "").strip():
        approval = await db.get(Approval, change_preview.approval_id)
        if approval is None:
            raise ValueError("The linked approval for this change preview no longer exists")
        return await resolve_chat_rerun_target_message_for_approval(
            db,
            session=session,
            approval=approval,
        )

    cutoff = change_preview.created_at
    ordered_messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )
        .scalars()
        .all()
    )
    fallback_user: Message | None = None
    for message in reversed(ordered_messages):
        if cutoff and message.created_at and message.created_at > cutoff:
            continue
        role = str(message.role or "").strip()
        if role == "assistant":
            return await resolve_chat_rerun_target_message(
                db,
                session=session,
                message=message,
            )
        if role == "user" and fallback_user is None:
            fallback_user = message
    if fallback_user is not None:
        return fallback_user
    raise ValueError("No preceding user message exists for this change preview")
