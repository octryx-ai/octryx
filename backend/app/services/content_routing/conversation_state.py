"""The sensitive categories a conversation already contained: principal.sensitive, sticky until cleared."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ContentConversationState
from ...time_utils import utc_now
from ..content_detection.scanner import ScanReport

logger = logging.getLogger(__name__)

CLAUDE_SESSION_HEADER = "x-claude-code-session-id"
CHAT_CONVERSATION = "chat"
SESSION_WIDE = "session"
_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def conversation_key(headers: Mapping[str, str]) -> str:
    value = str(headers.get(CLAUDE_SESSION_HEADER) or "")
    return value if _KEY.match(value) else SESSION_WIDE


@dataclass(frozen=True, slots=True)
class ConversationState:
    categories: frozenset[str] = frozenset()
    route_to: str = ""


EMPTY_STATE = ConversationState()


async def _row(db: AsyncSession, session_id: str, key: str) -> ContentConversationState | None:
    stmt = select(ContentConversationState).where(ContentConversationState.session_id == session_id,
                                                  ContentConversationState.conversation_key == key)
    return (await db.execute(stmt)).scalar_one_or_none()


async def load_state(session_id: str | None, key: str) -> ConversationState:
    if not session_id:
        return EMPTY_STATE
    from ...db import core as db_core

    try:
        async with db_core.async_session_factory() as db:
            row = await _row(db, session_id, key)
    except Exception:  # noqa: BLE001 - "nothing sensitive yet": the request is still decided on its own content
        logger.warning("content_conversation_state_read_failed", exc_info=True)
        return EMPTY_STATE
    if row is None:
        return EMPTY_STATE
    return ConversationState(frozenset(str(item) for item in row.categories or ()), str(row.route_to or ""))


async def remember(session_id: str | None, key: str, report: ScanReport, *, policy_id: str | None = None,
                   decision_id: str | None = None, route_to: str = "") -> None:
    if not session_id or (not report.categories and not route_to):
        return
    from ...db import core as db_core

    try:
        async with db_core.async_session_factory() as db:
            row = await _row(db, session_id, key)
            now = utc_now()
            if row is None:
                row = ContentConversationState(session_id=session_id, conversation_key=key, categories=[],
                                               detectors={}, first_at=now)
                db.add(row)
            counts = dict(row.detectors or {})
            for detector, count in report.counts().items():
                counts[detector] = int(counts.get(detector, 0)) + count
            row.categories = sorted(set(row.categories or ()) | report.categories)
            row.detectors = counts
            row.policy_id = row.policy_id or policy_id
            row.decision_id = row.decision_id or decision_id
            row.route_to = route_to or row.route_to
            row.updated_at = now
            await db.commit()
    except Exception:  # noqa: BLE001 - the request was decided on its own content; the badge may lag
        logger.warning("content_conversation_state_write_failed", exc_info=True)


async def latest_by_session(db: AsyncSession, session_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    wanted = [item for item in session_ids if item]
    if not wanted:
        return {}
    stmt = (select(ContentConversationState).where(ContentConversationState.session_id.in_(wanted))
            .order_by(ContentConversationState.updated_at.asc()))
    found: dict[str, dict[str, Any]] = {}
    for row in (await db.execute(stmt)).scalars():
        found[row.session_id] = {
            "categories": list(row.categories or []),
            "detectors": dict(row.detectors or {}),
            "since": row.first_at.isoformat() if row.first_at else None,
            "policy_id": row.policy_id,
            "route_to": row.route_to,
        }
    return found


__all__ = [
    "CHAT_CONVERSATION",
    "CLAUDE_SESSION_HEADER",
    "EMPTY_STATE",
    "SESSION_WIDE",
    "ConversationState",
    "conversation_key",
    "latest_by_session",
    "load_state",
    "remember",
]
