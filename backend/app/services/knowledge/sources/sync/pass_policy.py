"""When a Source Sync run begins a fresh header pass instead of resuming the open one.

A scheduled run is the interval's ACL and freshness check, so it must see every header of the pass it
completes within that interval. It therefore never resumes a pass

- that a manual run began (the items before its cursor missed this interval's check), or
- that any run since the last completed pass left unfinished: a run that **failed** (a listing error, a
  429 or a 500), one that **needed configuration**, or one that **crashed** (still ``running`` while it is
  not the current run). Looking at every such run, not only the connector's last one, keeps a manual run
  in between (Run now, stopped at its page bound) from masking the failure.

A pass left open only because runs hit their page bound (``MAX_PAGES_PER_RUN``) is resumed: the next
scheduled run continues it, so a very large source still completes passes. A manual run resumes any
open pass.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import (
    RUN_STATE_FAILED,
    RUN_STATE_NEEDS_CONFIGURATION,
    RUN_STATE_RUNNING,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from .cursor import SyncCursor

_UNFINISHED_STATES = frozenset({RUN_STATE_FAILED, RUN_STATE_NEEDS_CONFIGURATION, RUN_STATE_RUNNING})


def _instant(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


async def _an_open_pass_run_was_left_unfinished(
    db: AsyncSession, row: KnowledgeSourceConnector, cursor: SyncCursor
) -> bool:
    """Whether a run since the last completed pass failed, needed configuration or crashed."""
    statement = select(KnowledgeSourceSyncRun.state).where(KnowledgeSourceSyncRun.connector_id == row.id)
    since = _instant(cursor.last_pass_closed_at)
    if since is not None:
        statement = statement.where(KnowledgeSourceSyncRun.started_at > since)
    states = list((await db.execute(statement.order_by(KnowledgeSourceSyncRun.started_at))).scalars())
    if states and states[-1] == RUN_STATE_RUNNING:
        states.pop()  # the current run: it holds the lease, so it is the newest
    return any(state in _UNFINISHED_STATES for state in states)


async def begins_fresh_pass(
    db: AsyncSession, row: KnowledgeSourceConnector, cursor: SyncCursor, *, scheduled: bool
) -> bool:
    """Whether this run begins a fresh header pass (``True`` also when no pass is open)."""
    if not cursor.pass_open:
        return True
    if not scheduled:
        return False
    if not cursor.pass_scheduled:
        return True
    return await _an_open_pass_run_was_left_unfinished(db, row, cursor)


__all__ = ["begins_fresh_pass"]
