"""Recall: the memories of one Workspace a user may see, ranked lexically in PostgreSQL. Query terms are data, never
syntax; answer feedback needs its class named."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import case, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User
from ....models.project.knowledge_memory import KnowledgeMemoryItem, MemoryClass, MemoryState
from ....time_utils import utc_now
from ..access.authorization import AuthorizedWorkspace
from .errors import MemoryRefusedError
from .presentation import recall_entry
from .visibility import recallable, visible_to

MAX_RECALL_LIMIT = 20
DEFAULT_RECALL_LIMIT = 8
MAX_TERMS = 8
MAX_QUERY_CHARS = 500
_TERM = re.compile(r"\w+")
_LIKE_ESCAPE = "\\"
_CLASSES = frozenset(member.value for member in MemoryClass)


@dataclass(frozen=True, slots=True)
class RecallRequest:
    terms: tuple[str, ...]
    classes: tuple[str, ...]
    limit: int


def _escape_like(term: str) -> str:
    return term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")


def parse_recall_request(query: object, classes: object, limit: object) -> RecallRequest:
    if query is None:
        query = ""
    if type(query) is not str or len(query) > MAX_QUERY_CHARS:
        raise MemoryRefusedError("invalid_request")
    terms = tuple(dict.fromkeys(term for term in _TERM.findall(query.casefold()) if len(term) >= 2))[:MAX_TERMS]
    if classes is None:
        class_values: tuple[str, ...] = ()
    elif type(classes) is list and all(type(item) is str and item in _CLASSES for item in classes):
        class_values = tuple(dict.fromkeys(classes))
    else:
        raise MemoryRefusedError("invalid_request")
    if limit is None:
        limit = DEFAULT_RECALL_LIMIT
    if type(limit) is not int or not 1 <= limit <= MAX_RECALL_LIMIT:
        raise MemoryRefusedError("invalid_request")
    return RecallRequest(terms=terms, classes=class_values, limit=limit)


async def usernames(db: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.username).where(User.id.in_(sorted(user_ids))))
    return {str(user_id): str(username) for user_id, username in rows.all()}


async def recall(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, user_id: str, request: RecallRequest
) -> list[dict]:
    item = KnowledgeMemoryItem
    matched = [
        case((item.text.ilike(f"%{_escape_like(term)}%", escape=_LIKE_ESCAPE), 1), else_=0) for term in request.terms
    ]
    score = sum(matched[1:], matched[0]) if matched else literal(0)
    statement = select(item).where(visible_to(authorized.project_id, user_id), recallable(utc_now()))
    if request.classes:
        statement = statement.where(item.item_class.in_(request.classes))
    else:
        # Answer feedback answers only a recall that names its class explicitly.
        statement = statement.where(item.item_class != MemoryClass.ANSWER_FEEDBACK.value)
    if matched:
        statement = statement.where(score > 0)
    confirmed_first = case((item.state == MemoryState.CONFIRMED.value, 0), else_=1)
    statement = statement.order_by(score.desc(), confirmed_first, item.created_at.desc(), item.id).limit(request.limit)
    rows = list((await db.execute(statement)).scalars().all())
    names = await usernames(db, {row.author_user_id for row in rows if row.author_user_id})
    return [recall_entry(row, recorded_by=names.get(row.author_user_id or "")) for row in rows]


__all__ = ["DEFAULT_RECALL_LIMIT", "MAX_RECALL_LIMIT", "RecallRequest", "parse_recall_request", "recall"]
