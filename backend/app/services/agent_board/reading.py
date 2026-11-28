"""Reading the board: pages, threads, "addressed to me" and the unread count."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentBoardAck, AgentBoardMessage
from ..access_control import _user_is_admin
from ..project.service import get_project_access_details
from .envelope import RECIPIENT_AGENT

MAX_LIMIT = 100
DEFAULT_LIMIT = 50
THREAD_LIMIT = 500
CODE_CURSOR_INVALID = "cursor_invalid"


def limit_from(value: Any) -> int:
    if value is None or value == "":
        return DEFAULT_LIMIT
    if type(value) is not int or value < 1:
        raise HTTPException(status_code=422, detail="limit must be a positive integer")
    return min(value, MAX_LIMIT)


ROLE_ADMINS = "admins"
_ADMIN_ROLES = frozenset({"admin", "owner"})


@dataclass(frozen=True, slots=True)
class Addressee:
    agent_hash: str
    user_id: str
    admin_project_ids: frozenset[str] = frozenset()


async def addressee_for(db: AsyncSession, *, agent_hash: str, user_id: str, project_ids: Iterable[str]) -> Addressee:
    ids = set(project_ids)
    if await _user_is_admin(db, user_id):
        admin = ids
    else:
        access = await get_project_access_details(user_id, db)
        admin = {str(entry["id"]) for entry in access if entry.get("role") in _ADMIN_ROLES} & ids
    return Addressee(agent_hash, user_id, frozenset(admin))


def addressed_to_agent(addressee: Addressee):
    to_me = [
        AgentBoardMessage.to_agent_hash == addressee.agent_hash,
        and_(AgentBoardMessage.to_agent_hash.is_(None), AgentBoardMessage.to_user_id == addressee.user_id),
    ]
    if addressee.admin_project_ids:
        to_me.append(
            and_(
                AgentBoardMessage.to_role == ROLE_ADMINS,
                AgentBoardMessage.project_id.in_(sorted(addressee.admin_project_ids)),
            )
        )
    return and_(
        or_(
            AgentBoardMessage.author_agent_hash.is_(None),
            AgentBoardMessage.author_agent_hash != addressee.agent_hash,
        ),
        or_(*to_me),
    )


def acked_by(kind: str, ref: str):
    return exists().where(
        AgentBoardAck.message_id == AgentBoardMessage.id,
        AgentBoardAck.recipient_kind == kind,
        AgentBoardAck.recipient_ref == ref,
    )


async def read_page(
    db: AsyncSession,
    *,
    project_ids: Iterable[str],
    cursor: str | None = None,
    work_item_id: str | None = None,
    kind: str | None = None,
    agent_hash: str | None = None,
    addressed_to: Addressee | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[AgentBoardMessage], str | None]:
    ids = sorted(set(project_ids))
    if not ids:
        return [], None
    statement = select(AgentBoardMessage).where(AgentBoardMessage.project_id.in_(ids))
    if cursor:
        anchor = await db.get(AgentBoardMessage, cursor)
        if anchor is None or anchor.project_id not in ids:
            raise HTTPException(status_code=422, detail={"code": CODE_CURSOR_INVALID})
        statement = statement.where(
            or_(
                AgentBoardMessage.created_at < anchor.created_at,
                and_(AgentBoardMessage.created_at == anchor.created_at, AgentBoardMessage.id < anchor.id),
            )
        )
    if work_item_id:
        statement = statement.where(AgentBoardMessage.work_item_id == work_item_id)
    if kind:
        statement = statement.where(AgentBoardMessage.kind == kind)
    if agent_hash:
        statement = statement.where(
            or_(AgentBoardMessage.author_agent_hash == agent_hash, AgentBoardMessage.to_agent_hash == agent_hash)
        )
    if addressed_to is not None:
        statement = statement.where(addressed_to_agent(addressed_to))
    rows = (
        await db.execute(
            statement.order_by(AgentBoardMessage.created_at.desc(), AgentBoardMessage.id.desc()).limit(limit + 1)
        )
    ).scalars().all()
    page = list(rows[:limit])
    return page, page[-1].id if len(rows) > limit else None


async def thread_of(db: AsyncSession, message: AgentBoardMessage) -> tuple[AgentBoardMessage, list[AgentBoardMessage]]:
    root, seen = message, {message.id}
    while root.reply_to:
        parent = await db.get(AgentBoardMessage, root.reply_to)
        if parent is None or parent.id in seen or parent.project_id != message.project_id:
            break
        seen.add(parent.id)
        root = parent
    replies: list[AgentBoardMessage] = []
    frontier = [root.id]
    while frontier and len(replies) < THREAD_LIMIT:
        children = (
            await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.reply_to.in_(frontier)))
        ).scalars().all()
        children = [child for child in children if child.project_id == root.project_id]
        replies.extend(children)
        frontier = [child.id for child in children]
    replies.sort(key=lambda row: (row.created_at, row.id))
    return root, replies[:THREAD_LIMIT]


async def unread_for_agent(db: AsyncSession, *, agent_hash: str, user_id: str, project_id: str) -> int:
    addressee = await addressee_for(db, agent_hash=agent_hash, user_id=user_id, project_ids=[project_id])
    statement = select(func.count(AgentBoardMessage.id)).where(
        AgentBoardMessage.project_id == project_id,
        AgentBoardMessage.redacted_at.is_(None),
        addressed_to_agent(addressee),
        ~acked_by(RECIPIENT_AGENT, agent_hash),
    )
    return int((await db.execute(statement)).scalar_one() or 0)


__all__ = [
    "CODE_CURSOR_INVALID",
    "MAX_LIMIT",
    "Addressee",
    "addressee_for",
    "acked_by",
    "addressed_to_agent",
    "limit_from",
    "read_page",
    "thread_of",
    "unread_for_agent",
]
