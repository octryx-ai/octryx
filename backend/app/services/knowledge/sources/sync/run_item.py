"""One listed page and its items within a Source Sync run (the per-item steps of ``runner.py``'s module doc)."""

from __future__ import annotations

import functools
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import ITEM_STATE_FAILED, ITEM_STATE_INGESTED
from ...access.authorization import AuthorizedWorkspace
from ...code.facets import CodeFileFacet
from ...code.repository_index import upsert_file
from ...ingestion.code_ingest import ingest_code_source, prepared_code_text
from ...ingestion.media_types import is_sandboxed_media_type
from ...ingestion.sandboxed_ingest import ingest_sandboxed_source
from ...ingestion.text_ingest import ingest_text_source
from ...ledger.errors import EvidenceLedgerContractError, EvidenceLedgerError
from ...runtime import EvidenceRuntime
from ...text_safety import remove_unsafe_chars
from .acl_sync import apply_item_acl
from .contract import (
    ACL_AUDIENCE_RESTRICTED,
    ACL_AUDIENCE_SCOPE,
    REASON_ACL_UNRESOLVED,
    REASON_REMOVED_AT_SOURCE,
    REASON_SOURCE_CONTRACT_VIOLATION,
    ConnectorError,
    ListingPage,
    SourceConnector,
    SourceItem,
)
from .items import ConnectorRef, load_item, new_item, retire_item, source_key_for
from .provenance import item_instance
from .run_report import RunReport

MAX_VERSION_MARKER_CHARS = 80


async def _sync_page(
    db: AsyncSession,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    ref: ConnectorRef,
    connector: SourceConnector,
    page: ListingPage,
    pass_number: int,
    report: RunReport,
    actor_id: str | None,
    enforce: bool,
    fetch_budget: int | None = None,
) -> int:
    """Handle one listed page; returns how many items were fetched (the budget it spent, at most ``fetch_budget``)."""
    report.count_listed(page.items)
    fetched = 0
    for item in page.items:
        may_fetch = fetch_budget is None or fetched < fetch_budget
        fetched += await _sync_item(
            db, runtime, authorized, ref, connector, item, pass_number, report, actor_id, enforce, may_fetch
        )
    for external_id in page.deleted:
        await _retire_deleted(db, ref, external_id, report)
    for skipped in page.skipped:
        # Listed entries that are no items (a Jira version whose name is no version): reason only, once.
        if not report.repeats(str(skipped[0])[:MAX_VERSION_MARKER_CHARS]):
            report.record(str(skipped[0])[:MAX_VERSION_MARKER_CHARS], "skipped", reason=str(skipped[1])[:40])
    return fetched


async def _sync_item(
    db: AsyncSession,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    ref: ConnectorRef,
    connector: SourceConnector,
    item: SourceItem,
    pass_number: int,
    report: RunReport,
    actor_id: str | None,
    enforce: bool,
    may_fetch: bool = True,
) -> int:
    """Sync one item; returns 1 when its content was fetched (it spent budget), else 0.

    ``may_fetch`` False (a scheduled run past its budget): the ACL step and version check still run,
    but a needed fetch is deferred; the item keeps its old marker, so the next run fetches it.
    """
    seen = await _seen_item(db, ref, item, pass_number, report)
    if seen is None:
        return 0
    state, item_id = seen
    external_id = item.external_id
    passed, title = await _acl_step(db, ref, connector, state, item, report, enforce)
    if not passed:
        return 0
    marker = str(item.version_marker)[:MAX_VERSION_MARKER_CHARS]
    instance = item_instance(item)  # read from another instance: never "unchanged" by its marker alone
    if state.source_id is not None and state.version_marker == marker and state.source_instance == instance:
        state.last_outcome = "unchanged"
        await db.commit()
        report.record(external_id, "unchanged", title=title)
        return 0
    if not may_fetch:
        await db.commit()
        report.record(external_id, "deferred", title=title)
        return 0
    try:
        content = await connector.fetch(item)
    except ConnectorError as error:
        await _fail(db, state, external_id, title, error.reason, report)
        return 1
    digest = hashlib.sha256(content.data).hexdigest()
    if state.source_id is not None and state.content_sha256 == digest:
        state.version_marker, state.source_instance = marker, instance
        state.last_outcome = "unchanged"
        await db.commit()
        report.record(external_id, "unchanged", title=title)
        return 1
    # The item row is committed first: ingestion commits on its own, and a refusal rolls back.
    await db.commit()
    await _ingest_item(
        db, runtime, authorized, ref, item, content, state, item_id, title, digest, (marker, instance), report,
        actor_id,
    )
    return 1


async def _seen_item(db: AsyncSession, ref: ConnectorRef, item: SourceItem, pass_number: int, report: RunReport):
    """The item's ledger row marked seen in this pass with its id, or ``None`` when nothing more is to be done."""
    if type(item) is not SourceItem:
        report.record(None, "failed", reason=REASON_SOURCE_CONTRACT_VIOLATION)
        return None
    try:
        source_key_for(ref, item.external_id)
    except EvidenceLedgerContractError:
        report.record(None, "failed", reason=REASON_SOURCE_CONTRACT_VIOLATION)
        return None
    external_id = item.external_id
    state = await load_item(db, ref, external_id)
    if state is None:
        state = new_item(ref, external_id, state=ITEM_STATE_FAILED, outcome="listed")
        db.add(state)
    state.last_seen_pass = pass_number
    item_id = state.id
    if report.repeats(external_id):
        await db.commit()  # already handled by the change listing in this run; now marked seen
        return None
    return state, item_id


async def _acl_step(
    db: AsyncSession,
    ref: ConnectorRef,
    connector: SourceConnector,
    state,
    item: SourceItem,
    report: RunReport,
    enforce: bool,
) -> tuple[bool, str | None]:
    """The ACL step first: ``(False, None)`` when the item stops here, else ``(True, its report title)``."""
    external_id = item.external_id
    if item.acl.audience not in (ACL_AUDIENCE_SCOPE, ACL_AUDIENCE_RESTRICTED):
        await _fail(db, state, external_id, None, REASON_ACL_UNRESOLVED, report)
        return False, None
    acl = await apply_item_acl(
        db,
        connector=connector,
        project_id=ref.project_id,
        source_key=state.source_key,
        item=item,
        serves_source=state.source_id is not None,
        enforce=enforce,
    )
    if acl.withhold is not None:
        retired = await retire_item(db, state, withheld=True, outcome=acl.withhold)
        await db.commit()
        report.record(external_id, "skipped", reason=acl.withhold)
        if retired:
            report.counts["retired"] += 1
        return False, None
    # A restricted item's title stays out of the report, which every Workspace member reads.
    return True, (None if acl.restricted else item.title)


async def _ingest_item(
    db: AsyncSession,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    ref: ConnectorRef,
    item: SourceItem,
    content,
    state,
    item_id,
    title: str | None,
    digest: str,
    version: tuple[str, object],
    report: RunReport,
    actor_id: str | None,
) -> None:
    """Ingest the fetched bytes as one new revision and record the item (and a code file's index row)."""
    external_id = item.external_id
    code_file = content.code_file if type(content.code_file) is CodeFileFacet else None
    try:
        ingested = await _ingest(db, runtime, authorized, ref, item, content, code_file, actor_id)
    except EvidenceLedgerError as error:
        await db.rollback()
        state = await db.get(type(state), item_id)
        await _fail(db, state, external_id, title, error.state.value, report)
        return
    state = await db.get(type(state), item_id)
    if code_file is not None:
        # Flushes only; committed with the item below. Elements come from the revision's own text.
        await upsert_file(
            db,
            project_id=ref.project_id,
            connector_id=ref.id,
            path=code_file.path,
            blob_sha=code_file.blob_sha,
            commit_sha=code_file.commit,
            language=code_file.language,
            source_id=ingested.source_id,
            revision_id=ingested.revision_id,
            text=prepared_code_text(content.data, code_file.path),
        )
    outcome = "updated" if state.source_id is not None else "created"
    state.source_id = ingested.source_id
    state.content_sha256 = digest
    state.version_marker, state.source_instance = version
    state.document_role = item.role
    state.state = ITEM_STATE_INGESTED
    state.last_outcome = outcome
    await db.commit()
    report.record(external_id, outcome, title=title)


async def _ingest(db, runtime, authorized, ref: ConnectorRef, item: SourceItem, content, code_file, actor_id):
    """The ingestion of the item's kind: code, sandboxed documents, or text in-process."""
    if code_file is not None:
        ingest = functools.partial(ingest_code_source, language=code_file.language, path=code_file.path)
    elif is_sandboxed_media_type(content.media_type):
        ingest = functools.partial(ingest_sandboxed_source, declared_media_type=content.media_type)
    else:
        ingest = functools.partial(ingest_text_source, declared_media_type=content.media_type)
    return await ingest(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=source_key_for(ref, item.external_id),
        display_title=source_title(item.title),
        data=content.data,
        created_by=actor_id,
        source_url=item.source_url,
        source_changed_at=item.source_changed_at,
        # An item with its own product scope (a Jira release) replaces the connector's.
        products=list(item.products or ref.products) or None,
        version=item.version if item.products else ref.version,
    )


def source_title(title: str) -> str:
    """The item's title for the ledger, without invisible characters such as an emoji's variation selector U+FE0F
    (a Jira summary starting with the gear emoji). The ledger refuses such a title rather than strip it, which
    would fail the item on every pass and leave the source "never synced"."""
    return remove_unsafe_chars(title, allow_line_breaks=False)


async def _fail(db: AsyncSession, state, external_id: str, title: str | None, reason: str, report: RunReport) -> None:
    """Record a failed item. A source it served stays served at the revision it already had."""
    if state.source_id is None:
        state.state = ITEM_STATE_FAILED
    state.last_outcome = reason[:40]
    await db.commit()
    report.record(external_id, "failed", reason=reason, title=title)


async def _retire_deleted(db: AsyncSession, ref: ConnectorRef, external_id: object, report: RunReport) -> None:
    if type(external_id) is not str:
        return
    state = await load_item(db, ref, external_id)
    if state is None or state.source_id is None:
        return
    await retire_item(db, state, withheld=False, outcome=REASON_REMOVED_AT_SOURCE)
    await db.commit()
    report.record(external_id, "retired", reason=REASON_REMOVED_AT_SOURCE)
