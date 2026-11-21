"""A runtime use that the source system refuses as unauthenticated marks its connection ``failing``.

The connection page and the problems list read the same ``state`` / ``state_reason`` (``services/connections``,
``services/problems``): a Knowledge sync run ending in ``source_unauthorized``, an intake run Jira answers with HTTP
401 or an agent tool call whose result carries ``status_code`` 401 sets ``state = failing`` and a one-sentence
``state_reason`` naming the use. Only an explicit authentication refusal counts (no message matching); the next
connection test sets the state again (``ok`` or ``failing``). A disabled connection keeps ``disabled``.

Only real connections are marked (an id of ``connector_named_connections``); the default entry has no
row and keeps today's health checks. The reason names the use, never a value, URL or secret.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from ...time_utils import utc_now
from ..connections.error_sentences import RUNTIME_SENTENCES
from .routes_model import NamedConnectionRoutes, ResolvedNamedConnection

logger = logging.getLogger(__name__)

STATE_FAILING = "failing"
AUTH_STATUS = 401
USE_SENTENCES = RUNTIME_SENTENCES  # one sentence per use (``connections/error_sentences.py``)


async def record_runtime_failure(db: AsyncSession | None, connection_id: str | None, use: str) -> bool:
    """Mark the connection ``failing`` for ``use``; ``False`` when there is no such (active) connection."""
    if db is None or not connection_id:
        return False
    row = await db.get(ConnectorNamedConnection, str(connection_id))
    if row is None or row.is_active is False:
        return False
    row.state, row.state_reason, row.updated_at = STATE_FAILING, USE_SENTENCES[use], utc_now()
    await db.flush()
    logger.info("Connection marked failing by a runtime use: connection=%s use=%s", row.id, use)
    return True


def unauthenticated(result: Any) -> bool:
    return isinstance(result, dict) and "error" in result and result.get("status_code") == AUTH_STATUS


async def note_tool_result(db: AsyncSession | None, routes: NamedConnectionRoutes, tool: str,
                           target: ResolvedNamedConnection | None, result: Any) -> None:
    """After an agent tool call: an unauthenticated result marks the connection it ran on."""
    if not unauthenticated(result):
        return
    default = routes.default_of(tool)
    connection_id = target.id if target is not None else (default.id if default is not None else None)
    await record_runtime_failure(db, connection_id, "agent_tools")


__all__ = ["AUTH_STATUS", "USE_SENTENCES", "note_tool_result", "record_runtime_failure", "unauthenticated"]
