"""The change-listing accelerator of scheduled runs. An accelerator only, never the source of truth."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import KnowledgeSourceConnector
from .....time_utils import utc_now
from ...ledger.errors import InvalidEvidenceRequestError
from .contract import ConnectorError, ListingPage, SourceConnector
from .cursor import SyncCursor

TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"
MODE_FULL = "full"
MODE_INCREMENTAL = "incremental"
MODE_INCREMENTAL_FALLBACK = "incremental_fallback"
# CQL reads a date in the requesting account's time zone (up to UTC+14), so the window covers that
# offset plus a margin; a re-listed unchanged page costs a header, never a fetch.
CHANGES_SAFETY_WINDOW = timedelta(hours=15)


@dataclass(frozen=True, slots=True)
class AcceleratorOutcome:
    ok: bool
    spent: int


def _instant(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def accelerator_due(cursor: SyncCursor, connector: SourceConnector, trigger: str) -> bool:
    if trigger != TRIGGER_SCHEDULED or getattr(connector, "list_changed_items", None) is None:
        return False
    return _instant(cursor.changes_since) is not None


async def drive_accelerator(
    db: AsyncSession,
    *,
    connector_id: str,
    connector: SourceConnector,
    budget: int,
    page_size: int,
    max_pages: int,
    sync_page: Callable[[ListingPage, int], Awaitable[int]],
) -> AcceleratorOutcome:
    row = await db.get(KnowledgeSourceConnector, connector_id)
    cursor = SyncCursor.load(row.cursor)
    if not cursor.incremental_open:
        cursor = cursor.begin_incremental(utc_now())
        row.cursor = cursor.as_dict()
        await db.commit()
    since = _instant(cursor.changes_since) - CHANGES_SAFETY_WINDOW
    spent = 0
    for _ in range(max_pages):
        if budget - spent <= 0:
            break
        token = cursor.incremental_token
        limit = min(budget - spent, page_size)
        try:
            page = await connector.list_changed_items(token, since=since, limit=limit)
        except (ConnectorError, InvalidEvidenceRequestError, ValueError):
            page = None  # any per-page listing or link error: the header pass covers this run
        if type(page) is not ListingPage or len(page.items) > limit or (
            page.next_token is not None and page.next_token == token
        ):
            # Close the change listing; the change point stays, the header pass covers this run.
            row = await db.get(KnowledgeSourceConnector, connector_id)
            current = SyncCursor.load(row.cursor)
            row.cursor = current.as_dict() | {"incremental_started_at": None, "incremental_token": None}
            await db.commit()
            return AcceleratorOutcome(ok=False, spent=spent)
        spent += await sync_page(page, cursor.pass_number)
        cursor = cursor.at_incremental(page.next_token)
        row = await db.get(KnowledgeSourceConnector, connector_id)
        # Keep what the header pass may have written meanwhile (nothing in this run so far).
        row.cursor = SyncCursor.load(row.cursor).as_dict() | {
            "incremental_started_at": cursor.incremental_started_at,
            "incremental_token": cursor.incremental_token,
        }
        await db.commit()
        if page.next_token is None:
            row = await db.get(KnowledgeSourceConnector, connector_id)
            row.cursor = SyncCursor.load(row.cursor).complete_incremental().as_dict()
            await db.commit()
            break
    return AcceleratorOutcome(ok=True, spent=spent)


__all__ = [
    "CHANGES_SAFETY_WINDOW",
    "MODE_FULL",
    "MODE_INCREMENTAL",
    "MODE_INCREMENTAL_FALLBACK",
    "TRIGGER_MANUAL",
    "TRIGGER_SCHEDULED",
    "AcceleratorOutcome",
    "accelerator_due",
    "drive_accelerator",
]
