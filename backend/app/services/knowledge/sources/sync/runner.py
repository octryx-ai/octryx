"""The bounded Source Sync runner: one run of one connector into the evidence ledger.

A run holds the connector's lease, resumes the open listing pass at the stored cursor, and handles
at most ``max_items_per_run`` item headers. Per item, in this order:

1. **ACL first** (``acl_sync.py``). The item's restriction is stored in the ledger before
   anything else. A restricted item is ingested with it only when the Workspace enforces source
   ACLs and the connector expanded it; otherwise it is withheld (``restricted_acl`` or
   ``acl_unresolved``) and a source it served until now is retired. An item whose ACL is unknown
   is a failure. Neither is ever fetched, and no restricted item's title reaches the report.
2. **Version marker.** An item still served at the same external version is unchanged, unfetched.
3. **Content hash.** Fetched bytes identical to what was ingested are unchanged: no revision.
4. **Ingestion.** Otherwise the bytes become one new revision, through the Docling sandbox for HTML
   and documents and in-process for text, carrying the deep link and the configured product scope.
   A repository file (``ItemContent.code_file``) is ingested as code, with line-ranged spans
   (``ingestion/code_ingest.py``), and recorded in the repository file index.

Skipped entries are counted per fixed reason too (``skipped_reasons``), so a repository run says how
many files were ``excluded``, ``skipped_binary`` or ``skipped_too_large``.

One item's failure records its fixed reason and never stops the run. A listing failure ends the
run early as ``failed`` and keeps the cursor where it was. Only when a pass completes are the items
it did not list any more retired: a stopped pass never looks like a deletion. The cursor is saved
after every page, so a run that dies is resumed, not restarted.

**Budget.** ``max_items_per_run`` counts the items whose content a run fetched, not the
unchanged headers it listed; a page never lists more than the remaining budget, and a run lists at
most ``MAX_PAGES_PER_RUN`` pages. A manual run stops when its budget is spent. A *scheduled* run keeps
listing headers (ACL and version for every served item) and defers only the fetches beyond its
budget (``deferred``); a deferred or failed item keeps the pass from counting as a clean
reconciliation, so its change stays in the next window.

**Incremental runs (``incremental.py``).** A scheduled run lists only the changes since
the last full pass while that pass is recent; otherwise, on a manual run, or when the change
listing fails, it reconciles fully. ``report.mode`` says which one ran; ``report.withheld`` counts
the restricted items not ingested.

**A completed run with a reason**. A connector may name why a completed pass listed what it did
through an optional ``completed_reason`` attribute (one fixed reason, never free text): a repository without any
commit completes with ``repository_empty`` and 0 items. The run stays ``completed`` — not a failure, no problem.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import (
    RUN_STATE_BUDGET_EXHAUSTED,
    RUN_STATE_COMPLETED,
    RUN_STATE_FAILED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from .....time_utils import utc_now
from ...access.authorization import AuthorizedWorkspace
from ...access.source_acl import acl_enforcement_enabled
from ...ledger.errors import EvidenceLedgerContractError
from ...runtime import EvidenceRuntime
from .contract import (
    REASON_LISTING_STALLED,
    REASON_REPOSITORY_EMPTY,
    REASON_RUN_IN_PROGRESS,
    REASON_SOURCE_CONTRACT_VIOLATION,
    ConnectorError,
    ListingPage,
    SourceConnector,
)
from .cursor import SyncCursor
from .incremental import (
    MODE_INCREMENTAL,
    MODE_INCREMENTAL_FALLBACK,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    accelerator_due,
    drive_accelerator,
)
from .items import ConnectorRef
from .pass_policy import begins_fresh_pass
from .run_finish import _finish, _reconcile
from .run_item import _sync_page
from .run_report import RunReport

logger = logging.getLogger(__name__)

RUN_LEASE = timedelta(minutes=30)
# Read through this module at run time, so a test can narrow a run by patching them here.
PAGE_SIZE = 50
MAX_PAGES_PER_RUN = 100


class SyncRefusedError(Exception):
    """The run was not started; ``reason`` is a fixed reason from ``contract.py``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _acquire_lease(db: AsyncSession, connector_id: str) -> bool:
    now = utc_now()
    result = await db.execute(
        update(KnowledgeSourceConnector)
        .where(
            KnowledgeSourceConnector.id == connector_id,
            or_(KnowledgeSourceConnector.run_lease_until.is_(None), KnowledgeSourceConnector.run_lease_until < now),
        )
        .values(run_lease_until=now + RUN_LEASE)
    )
    await db.commit()
    return result.rowcount == 1


async def run_source_sync(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    connector_row: KnowledgeSourceConnector,
    connector: SourceConnector,
    actor_id: str | None,
    trigger: str = TRIGGER_MANUAL,
) -> KnowledgeSourceSyncRun:
    """Run one bounded sync of ``connector_row`` and return its recorded run."""
    if type(authorized) is not AuthorizedWorkspace or not authorized.may_author:
        raise EvidenceLedgerContractError()
    if connector_row.project_id != authorized.project_id or connector.kind != connector_row.kind:
        raise EvidenceLedgerContractError()
    ref = ConnectorRef.of(connector_row)
    if not await _acquire_lease(db, ref.id):
        raise SyncRefusedError(REASON_RUN_IN_PROGRESS)
    run = KnowledgeSourceSyncRun(connector_id=ref.id, project_id=ref.project_id, triggered_by=actor_id)
    db.add(run)
    await db.commit()
    run_id = run.id
    report = RunReport()
    report.attach_scopes(connector)
    state, reason = RUN_STATE_FAILED, REASON_SOURCE_CONTRACT_VIOLATION
    try:
        state, reason = await _drive(db, runtime, authorized, ref, connector, report, actor_id, trigger)
    except Exception:
        await db.rollback()
        logger.error("Knowledge source sync run aborted by an unexpected error: workspace=%s", ref.project_id)
        raise
    finally:
        await _finish(db, ref, run_id, state, reason, report, actor_id)
    return await db.get(KnowledgeSourceSyncRun, run_id)


async def _drive(
    db: AsyncSession,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    ref: ConnectorRef,
    connector: SourceConnector,
    report: RunReport,
    actor_id: str | None,
    trigger: str = TRIGGER_MANUAL,
) -> tuple[str, str | None]:
    row = await db.get(KnowledgeSourceConnector, ref.id)
    cursor = SyncCursor.load(row.cursor)
    enforce = await acl_enforcement_enabled(db, ref.project_id)
    report.acl_enforced = enforce
    scheduled = trigger == TRIGGER_SCHEDULED
    budget = ref.max_items_per_run
    if accelerator_due(cursor, connector, trigger):
        budget, row, cursor = await _accelerate(
            db, runtime, authorized, ref, connector, report, actor_id, enforce, budget
        )
    if await begins_fresh_pass(db, row, cursor, scheduled=scheduled):
        # A scheduled run never resumes a pass a manual run began or a failed run left open.
        cursor = cursor.begin_pass(utc_now(), scheduled=scheduled)
        row.cursor = cursor.as_dict()
        await db.commit()
    for _ in range(MAX_PAGES_PER_RUN):
        if budget <= 0 and not scheduled:
            break
        token = cursor.token
        # A scheduled run lists full header pages whatever its budget; the budget only limits fetches.
        limit = PAGE_SIZE if scheduled else min(budget, PAGE_SIZE)
        try:
            page = await connector.list_items(token, limit=limit)
        except ConnectorError as error:
            return RUN_STATE_FAILED, error.reason
        refused = _page_refusal(page, token, limit)
        if refused is not None:
            return RUN_STATE_FAILED, refused
        unfinished_before = report.unfinished
        budget -= await _sync_page(
            db, runtime, authorized, ref, connector, page, cursor.pass_number, report, actor_id, enforce,
            fetch_budget=max(budget, 0),
        )
        cursor = await _save_page_cursor(db, ref, cursor, page, report.unfinished - unfinished_before)
        if page.next_token is None:
            await _complete_pass(db, ref, cursor, report)
            return RUN_STATE_COMPLETED, _completed_reason(connector)
    return RUN_STATE_BUDGET_EXHAUSTED, None


async def _accelerate(
    db: AsyncSession,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    ref: ConnectorRef,
    connector: SourceConnector,
    report: RunReport,
    actor_id: str | None,
    enforce: bool,
    budget: int,
) -> tuple[int, KnowledgeSourceConnector, SyncCursor]:
    """Changed pages first (CQL); never the only source of truth. The budget left, the row and cursor after it."""
    report.mode = MODE_INCREMENTAL
    outcome = await drive_accelerator(
        db,
        connector_id=ref.id,
        connector=connector,
        budget=budget,
        page_size=PAGE_SIZE,
        max_pages=MAX_PAGES_PER_RUN,
        sync_page=lambda page, pass_number: _sync_page(
            db, runtime, authorized, ref, connector, page, pass_number, report, actor_id, enforce
        ),
    )
    budget -= outcome.spent
    if not outcome.ok:
        report.mode = MODE_INCREMENTAL_FALLBACK
    row = await db.get(KnowledgeSourceConnector, ref.id)
    return budget, row, SyncCursor.load(row.cursor)


def _page_refusal(page: object, token: str | None, limit: int) -> str | None:
    """The fixed reason a listed page ends the run as failed, else ``None``."""
    if type(page) is not ListingPage or len(page.items) > limit:
        return REASON_SOURCE_CONTRACT_VIOLATION
    if page.next_token is not None and page.next_token == token:
        return REASON_LISTING_STALLED
    return None


async def _save_page_cursor(
    db: AsyncSession, ref: ConnectorRef, cursor: SyncCursor, page: ListingPage, unfinished: int
) -> SyncCursor:
    """Store the cursor after every page, so a run that dies is resumed, not restarted."""
    cursor = cursor.at(page.next_token).with_failures(unfinished)
    row = await db.get(KnowledgeSourceConnector, ref.id)
    row.cursor = SyncCursor.load(row.cursor).as_dict() | {
        "token": cursor.token,
        "pass_failures": cursor.pass_failures,
    }
    await db.commit()
    return cursor


async def _complete_pass(db: AsyncSession, ref: ConnectorRef, cursor: SyncCursor, report: RunReport) -> None:
    # Every completed listing pass retires what it no longer listed.
    await _reconcile(db, ref, cursor.pass_number, report)
    row = await db.get(KnowledgeSourceConnector, ref.id)
    row.cursor = SyncCursor.load(row.cursor).complete_pass(utc_now()).as_dict()
    await db.commit()
    report.pass_completed = True


def _completed_reason(connector: SourceConnector) -> str | None:
    """The connector's fixed reason for a completed pass (``repository_empty``), else ``None`` (module doc)."""
    reason = getattr(connector, "completed_reason", None)
    return reason if isinstance(reason, str) and reason == REASON_REPOSITORY_EMPTY else None


__all__ = [
    "SyncRefusedError",
    "run_source_sync",
]
