"""Writing to the board: posts, acknowledgements, decisions, redaction."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentBoardAck, AgentBoardMessage, AuditLog, WorkItem
from ...time_utils import utc_now
from ..access_control import _user_is_admin, get_project_role_for_user
from .envelope import KIND_DECISION, KIND_DECISION_REQUEST
from .message_rules import _optional_text, _refuse, body_from, options_from, refuse_secrets

KINDS = frozenset({
    "question", "answer", "info", "conflict", "handoff_request", "handoff_accept", KIND_DECISION_REQUEST,
    KIND_DECISION,
})
AGENT_KINDS = KINDS - {KIND_DECISION}
AUTHOR_AGENT = "agent"
AUTHOR_HUMAN = "human"
ROLE_ADMINS = "admins"
ADMIN_ROLES = frozenset({"admin", "owner"})
MAX_ACK_IDS = 100
_AGENT_HASH = re.compile(r"^[0-9a-f]{24}$")

CODE_ALREADY_DECIDED = "already_decided"
CODE_NOT_A_DECISION_REQUEST = "not_a_decision_request"
REDACT_AUDIT_ACTION = "agent_board.message.redacted"


@dataclass(frozen=True, slots=True)
class Author:
    type: str
    user_id: str
    agent_hash: str | None = None



async def is_workspace_admin(db: AsyncSession, user_id: str, project_id: str) -> bool:
    return await get_project_role_for_user(db, user_id, project_id) in ADMIN_ROLES


async def _require_addressee(db: AsyncSession, user_id: str, project_id: str) -> None:
    if await get_project_role_for_user(db, user_id, project_id) is None:
        raise _refuse("to_user_id is not a member of this Workspace")


async def post_message(
    db: AsyncSession,
    *,
    project_id: str,
    author: Author,
    arguments: dict[str, Any],
    allowed_kinds: frozenset[str] = AGENT_KINDS,
) -> AgentBoardMessage:
    kind = arguments.get("kind")
    if kind not in allowed_kinds:
        raise _refuse(f"kind must be one of {sorted(allowed_kinds)}")
    body = body_from(arguments.get("body"))
    options = options_from(arguments.get("options"), kind)
    to_role = _optional_text(arguments.get("to_role"), "to_role")
    if to_role not in (None, ROLE_ADMINS):
        raise _refuse("to_role must be 'admins'")
    to_agent_hash = _optional_text(arguments.get("to_agent_hash"), "to_agent_hash")
    if to_agent_hash is not None and not _AGENT_HASH.match(to_agent_hash):
        raise _refuse("to_agent_hash must be a 24-character agent hash")
    to_user_id = _optional_text(arguments.get("to_user_id"), "to_user_id")
    if to_user_id is not None:
        await _require_addressee(db, to_user_id, project_id)
    work_item_id = _optional_text(arguments.get("work_item_id"), "work_item_id")
    if work_item_id is not None:
        item = await db.get(WorkItem, work_item_id)
        if item is None or item.project_id != project_id:
            raise _refuse("Work item not found", 404)
    reply_to = _optional_text(arguments.get("reply_to"), "reply_to")
    if reply_to is not None:
        parent = await db.get(AgentBoardMessage, reply_to)
        if parent is None or parent.project_id != project_id:
            raise _refuse("Message not found", 404)
    refuse_secrets(body, *options)
    message = AgentBoardMessage(
        id=str(uuid.uuid4()),
        project_id=project_id,
        work_item_id=work_item_id,
        reply_to=reply_to,
        author_type=author.type,
        author_user_id=author.user_id,
        author_agent_hash=author.agent_hash,
        on_behalf_of_user_id=author.user_id if author.type == AUTHOR_AGENT else None,
        kind=kind,
        to_user_id=to_user_id,
        to_agent_hash=to_agent_hash,
        to_role=to_role,
        body=body,
        options=options,
        created_at=utc_now(),
    )
    db.add(message)
    await db.flush()
    from ..workflow_runs.teamwork.coordinator import board_posted

    await board_posted(db, message)  # teamwork: a post to a running split's coordinator wakes it (once)
    return message


async def acknowledge(
    db: AsyncSession, *, message_ids: Any, project_ids: Sequence[str], kind: str, ref: str, user_id: str
) -> int:
    if not isinstance(message_ids, list) or not message_ids or len(message_ids) > MAX_ACK_IDS:
        raise _refuse(f"message_ids must be a list of 1 to {MAX_ACK_IDS} ids")
    wanted = sorted({str(value) for value in message_ids if isinstance(value, str) and value})
    readable = (
        await db.execute(
            select(AgentBoardMessage.id).where(
                AgentBoardMessage.id.in_(wanted), AgentBoardMessage.project_id.in_(sorted(set(project_ids)))
            )
        )
    ).scalars().all()
    done = set(
        (
            await db.execute(
                select(AgentBoardAck.message_id).where(
                    AgentBoardAck.message_id.in_(readable),
                    AgentBoardAck.recipient_kind == kind,
                    AgentBoardAck.recipient_ref == ref,
                )
            )
        ).scalars().all()
    )
    now = utc_now()
    for message_id in readable:
        if message_id not in done:
            db.add(AgentBoardAck(id=str(uuid.uuid4()), message_id=message_id, recipient_kind=kind, recipient_ref=ref,
                                 recipient_user_id=user_id, acked_at=now))
    await db.flush()
    return len(readable)


def _unaddressed(message: AgentBoardMessage) -> bool:
    return message.to_user_id is None and message.to_agent_hash is None and message.to_role is None


async def may_decide(db: AsyncSession, message: AgentBoardMessage, user_id: str) -> bool:
    if message.to_user_id == user_id or await _user_is_admin(db, user_id):
        return True
    if message.to_role == ROLE_ADMINS or _unaddressed(message):
        return await is_workspace_admin(db, user_id, message.project_id)
    return False


async def existing_decision(db: AsyncSession, request_id: str) -> AgentBoardMessage | None:
    statement = select(AgentBoardMessage).where(
        AgentBoardMessage.reply_to == request_id, AgentBoardMessage.kind == KIND_DECISION
    )
    return (await db.execute(statement)).scalars().first()


async def decide(
    db: AsyncSession, *, request: AgentBoardMessage, user_id: str, option: Any, text: Any
) -> AgentBoardMessage:
    if request.kind != KIND_DECISION_REQUEST or request.redacted_at is not None:
        raise _refuse({"code": CODE_NOT_A_DECISION_REQUEST}, 409)
    if not await may_decide(db, request, user_id):
        raise _refuse("You may not decide this request", 403)
    chosen = _optional_text(option, "option")
    note = body_from(text, required=False).strip()
    if chosen is None and not note:
        raise _refuse("option or text is required")
    if chosen is not None and chosen not in (request.options or []):
        raise _refuse("option must be one of the request's options")
    refuse_secrets(note)
    if await existing_decision(db, request.id) is not None:
        raise _refuse({"code": CODE_ALREADY_DECIDED}, 409)
    decision = AgentBoardMessage(
        id=str(uuid.uuid4()),
        project_id=request.project_id,
        work_item_id=request.work_item_id,
        reply_to=request.id,
        author_type=AUTHOR_HUMAN,
        author_user_id=user_id,
        kind=KIND_DECISION,
        # The decision goes back to whoever asked.
        to_user_id=request.author_user_id,
        to_agent_hash=request.author_agent_hash,
        body=note,
        options=[chosen] if chosen is not None else [],
        created_at=utc_now(),
    )
    try:
        async with db.begin_nested():
            db.add(decision)
            await db.flush()
    except IntegrityError:
        raise _refuse({"code": CODE_ALREADY_DECIDED}, 409) from None
    return decision


async def redact(db: AsyncSession, *, message: AgentBoardMessage, actor_user_id: str) -> AgentBoardMessage:
    if message.redacted_at is None:
        message.body = ""
        message.options = []
        message.redacted_at = utc_now()
        message.redacted_by = actor_user_id
        details: dict[str, Any] = {"project_id": message.project_id, "kind": message.kind}
        decision = await existing_decision(db, message.id) if message.kind == KIND_DECISION_REQUEST else None
        if decision is not None:
            decision.body = ""
            decision.options = []
            details["cascaded_decision_id"] = decision.id
        db.add(
            AuditLog(
                user_id=actor_user_id,
                action=REDACT_AUDIT_ACTION,
                resource_type="agent_board_message",
                resource_id=message.id,
                project_id=message.project_id,
                details=details,
            )
        )
        await db.flush()
    return message


__all__ = [
    "AGENT_KINDS",
    "AUTHOR_AGENT",
    "AUTHOR_HUMAN",
    "CODE_ALREADY_DECIDED",
    "KINDS",
    "REDACT_AUDIT_ACTION",
    "Author",
    "acknowledge",
    "decide",
    "existing_decision",
    "is_workspace_admin",
    "may_decide",
    "post_message",
    "redact",
]
