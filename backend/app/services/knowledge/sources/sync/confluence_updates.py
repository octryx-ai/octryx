"""Which Confluence pages changed recently, read from the Source Sync ledger, with no other store or fallback."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_CONFLUENCE,
    ITEM_STATE_INGESTED,
    ITEM_STATE_RETIRED,
    RUN_STATE_BUDGET_EXHAUSTED,
    RUN_STATE_COMPLETED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
    KnowledgeSourceSyncRun,
)
from .....time_utils import utc_now
from ...access.authorization import AuthorizedWorkspace
from ...access.source_acl import visible_source

DEFAULT_DAYS = 7
MAX_DAYS = 90
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_CONNECTORS = 20
# Revisions read per call before grouping by page; the answer says when this bound cut it.
MAX_REVISION_ROWS = 500
REASON_NOT_CONFIGURED = "confluence_sync_not_configured"
REASON_NEVER_RAN = "confluence_sync_never_ran"
FINISHED_RUN_STATES = (RUN_STATE_COMPLETED, RUN_STATE_BUDGET_EXHAUSTED)
SOURCE_LABEL = "Confluence Source Sync ledger"


def _bounded(raw: object, default: int, maximum: int) -> int | None:
    if raw is None:
        return default
    if type(raw) is not int or not 1 <= raw <= maximum:
        return None
    return raw


def _version(marker: str | None) -> int | None:
    return int(marker) if marker and marker.isdigit() else None


async def _connector_ids(db: AsyncSession, project_id: str) -> list[str]:
    rows = await db.execute(
        select(KnowledgeSourceConnector.id)
        .where(
            KnowledgeSourceConnector.project_id == project_id,
            KnowledgeSourceConnector.kind == CONNECTOR_KIND_CONFLUENCE,
        )
        .order_by(KnowledgeSourceConnector.connector_key)
        .limit(MAX_CONNECTORS)
    )
    return [str(row) for row in rows.scalars()]


async def _last_run(db: AsyncSession, project_id: str, connector_ids: list[str]) -> tuple[object, str] | None:
    row = (
        await db.execute(
            select(KnowledgeSourceSyncRun.finished_at, KnowledgeSourceSyncRun.state)
            .where(
                KnowledgeSourceSyncRun.project_id == project_id,
                KnowledgeSourceSyncRun.connector_id.in_(connector_ids),
                KnowledgeSourceSyncRun.state.in_(FINISHED_RUN_STATES),
                KnowledgeSourceSyncRun.finished_at.is_not(None),
            )
            .order_by(KnowledgeSourceSyncRun.finished_at.desc())
            .limit(1)
        )
    ).first()
    return None if row is None else (row[0], str(row[1]))


def _items(project_id: str, connector_ids: list[str]):
    return (
        KnowledgeSourceSyncItem.project_id == project_id,
        KnowledgeSourceSyncItem.connector_id.in_(connector_ids),
    )


async def _changed_pages(
    db: AsyncSession, authorized: AuthorizedWorkspace, connector_ids: list[str], since
) -> tuple[list[dict], list[dict], bool]:
    project_id = authorized.project_id
    rows = (
        await db.execute(
            select(
                KnowledgeSourceSyncItem.external_id,
                KnowledgeSourceSyncItem.version_marker,
                KnowledgeEvidenceSource.display_title,
                KnowledgeSourceRevision.revision_ordinal,
                KnowledgeSourceRevision.created_at,
                KnowledgeSourceRevisionOrigin.source_url,
            )
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceSyncItem.source_id)
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.source_id == KnowledgeEvidenceSource.id)
            .outerjoin(
                KnowledgeSourceRevisionOrigin, KnowledgeSourceRevisionOrigin.revision_id == KnowledgeSourceRevision.id
            )
            .where(
                *_items(project_id, connector_ids),
                KnowledgeSourceSyncItem.state == ITEM_STATE_INGESTED,
                KnowledgeEvidenceSource.project_id == project_id,
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeSourceRevision.created_at >= since,
                visible_source(project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
            )
            .order_by(KnowledgeSourceRevision.created_at.desc(), KnowledgeSourceRevision.revision_ordinal.desc())
            .limit(MAX_REVISION_ROWS + 1)
        )
    ).all()
    truncated = len(rows) > MAX_REVISION_ROWS
    pages: dict[str, dict] = {}
    for external_id, marker, title, ordinal, created_at, source_url in rows[:MAX_REVISION_ROWS]:
        page = pages.get(external_id)
        if page is None:
            # Newest first: the first row of a page is its latest revision inside the window.
            pages[external_id] = page = {
                "id": external_id,
                "title": title,
                "url": source_url,
                "current_version": _version(marker),
                "revision": int(ordinal),
                "recorded_at": created_at.isoformat() if created_at else None,
                "revisions_in_window": 0,
                "first_recorded_in_window": False,
            }
        page["revisions_in_window"] += 1
        if int(ordinal) == 1:
            page["first_recorded_in_window"] = True
    new = [page for page in pages.values() if page.pop("first_recorded_in_window")]
    changed = [page for page in pages.values() if page not in new]
    return new, changed, truncated


async def _removed_pages(
    db: AsyncSession, authorized: AuthorizedWorkspace, connector_ids: list[str], since, limit: int
) -> list[dict]:
    project_id = authorized.project_id
    rows = await db.execute(
        select(
            KnowledgeSourceSyncItem.external_id,
            KnowledgeSourceSyncItem.last_outcome,
            KnowledgeSourceSyncItem.updated_at,
            KnowledgeEvidenceSource.display_title,
        )
        .join(
            KnowledgeEvidenceSource,
            (KnowledgeEvidenceSource.source_key == KnowledgeSourceSyncItem.source_key)
            & (KnowledgeEvidenceSource.project_id == project_id),
        )
        .where(
            *_items(project_id, connector_ids),
            KnowledgeSourceSyncItem.state == ITEM_STATE_RETIRED,
            KnowledgeSourceSyncItem.updated_at >= since,
            visible_source(project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
        )
        .order_by(KnowledgeSourceSyncItem.updated_at.desc())
        .limit(limit)
    )
    return [
        {"id": external_id, "title": title, "reason": outcome, "recorded_at": updated.isoformat() if updated else None}
        for external_id, outcome, updated, title in rows.all()
    ]


async def _served_count(db: AsyncSession, authorized: AuthorizedWorkspace, connector_ids: list[str]) -> int:
    project_id = authorized.project_id
    statement = (
        select(func.count(KnowledgeSourceSyncItem.id))
        .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceSyncItem.source_id)
        .where(
            *_items(project_id, connector_ids),
            KnowledgeSourceSyncItem.state == ITEM_STATE_INGESTED,
            KnowledgeEvidenceSource.project_id == project_id,
            visible_source(project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
        )
    )
    return int((await db.execute(statement)).scalar_one() or 0)


async def confluence_page_updates(
    db: AsyncSession, authorized: AuthorizedWorkspace, *, days: object = None, limit: object = None
) -> dict[str, object]:
    window = _bounded(days, DEFAULT_DAYS, MAX_DAYS)
    bound = _bounded(limit, DEFAULT_LIMIT, MAX_LIMIT)
    if window is None or bound is None:
        return {"state": "invalid_request", "reason": "invalid_request"}
    project_id = authorized.project_id
    connector_ids = await _connector_ids(db, project_id)
    if not connector_ids:
        return {"state": "needs_configuration", "reason": REASON_NOT_CONFIGURED}
    last_run = await _last_run(db, project_id, connector_ids)
    if last_run is None:
        return {"state": "needs_configuration", "reason": REASON_NEVER_RAN}
    since = utc_now() - timedelta(days=window)
    new, changed, truncated = await _changed_pages(db, authorized, connector_ids, since)
    removed = await _removed_pages(db, authorized, connector_ids, since, bound)
    total = await _served_count(db, authorized, connector_ids)
    finished_at, run_state = last_run
    return {
        "state": "ok",
        "source": SOURCE_LABEL,
        "workspace_id": project_id,
        "window_days": window,
        "since": since.isoformat(),
        "synced_through": finished_at.isoformat() if finished_at else None,
        # A budget-exhausted last run did not visit every page; the feed may miss recent changes.
        "last_sync_complete": run_state == RUN_STATE_COMPLETED,
        "total_pages": total,
        "new_count": len(new),
        "changed_count": len(changed),
        "removed_count": len(removed),
        "unchanged_count": max(total - len(new) - len(changed), 0),
        "new_pages": new[:bound],
        "changed_pages": changed[:bound],
        "removed_pages": removed,
        "complete": not truncated and len(new) <= bound and len(changed) <= bound,
    }


__all__ = ["REASON_NEVER_RAN", "REASON_NOT_CONFIGURED", "confluence_page_updates"]
