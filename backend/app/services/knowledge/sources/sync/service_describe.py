"""How the Source Sync connectors of one Workspace and their runs are described to the route layer."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KIND_JIRA,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from .....time_utils import utc_now
from ...access.authorization import AuthorizedWorkspace
from ..repository_git_token import git_token_state
from ..repository_snapshot.labels import display_label
from .cursor import SyncCursor
from .git_autolink import describe_candidates, git_connection_candidates
from .git_config import ACCESS_MODE
from .items import served_item_count
from .jira_release_config import release_sync_state
from .kinds import KINDS
from .utc import utc_iso

MAX_CONNECTORS_LISTED = 50
CURSOR_TIME_FIELDS = ("pass_started_at", "last_completed_at", "changes_since", "incremental_started_at",
                      "last_pass_closed_at")


async def connection_candidates(db: AsyncSession, project_id: str, scope: dict | None) -> list[dict[str, str]]:
    """The usable connections that could read an unlinked repository source (id, name, type), for the picker."""
    return describe_candidates(await git_connection_candidates(db, project_id, scope))


def describe_run(run: KnowledgeSourceSyncRun | None, *, with_outcomes: bool = False) -> dict | None:
    if run is None:
        return None
    described = {
        "id": run.id,
        "state": run.state,
        "reason": run.reason,
        "report": dict(run.report or {}),
        "started_at": utc_iso(run.started_at),
        "finished_at": utc_iso(run.finished_at),
    }
    if with_outcomes:
        described["outcomes"] = list(run.outcomes or [])
    return described


async def last_run(db: AsyncSession, row: KnowledgeSourceConnector) -> KnowledgeSourceSyncRun | None:
    if row.last_run_id is None:
        return None
    run = await db.get(KnowledgeSourceSyncRun, row.last_run_id)
    return run if run is not None and run.connector_id == row.id else None


def _described_cursor(cursor: SyncCursor) -> dict:
    described = cursor.as_dict()
    return described | {key: utc_iso(described[key]) for key in CURSOR_TIME_FIELDS}


def _freshness(cursor: SyncCursor) -> dict:
    """When the source was last fully reconciled; every time in UTC with offset.

    ``last_full_pass_at`` is the last *clean* listing pass (no failed or deferred item): deletions,
    moves and ACL changes are reconciled at least then. ``last_pass_closed_at`` and
    ``last_pass_failures`` describe the last closed pass, clean or not. "Run now" always runs the
    header listing pass (never the change accelerator), resuming an open pass.
    """
    return {
        "last_full_pass_at": utc_iso(cursor.last_completed_at),
        "last_pass_closed_at": utc_iso(cursor.last_pass_closed_at),
        "last_pass_failures": cursor.last_pass_failures,
        "full_pass_in_progress": cursor.pass_open,
        "full_pass_started_at": utc_iso(cursor.pass_started_at),
        "changes_since": utc_iso(cursor.changes_since),
        "run_now_full_pass": True,
    }


async def describe_connector(db: AsyncSession, row: KnowledgeSourceConnector) -> dict:
    cursor = SyncCursor.load(row.cursor)
    described = {
        "connector_key": row.connector_key,
        "kind": row.kind,
        "scope": dict(row.scope or {}),
        "products": list(row.products or []),
        "version": row.version,
        "max_items_per_run": row.max_items_per_run,
        "state": row.state,
        "cursor": _described_cursor(cursor),
        "schedule": {
            "enabled": bool(row.schedule_enabled),
            "interval_minutes": row.schedule_interval_minutes,
            "next_run_at": utc_iso(row.next_scheduled_at),
        },
        "freshness": _freshness(cursor),
        "running": row.run_lease_until is not None and row.run_lease_until > utc_now(),
        "last_run": describe_run(await last_run(db, row)),
        # The items it serves to search now, the same count for synced runs and launcher snapshots.
        "served_items": await served_item_count(db, row),
    }
    if row.kind == CONNECTOR_KIND_GIT_REPOSITORY:
        # "<name> (<version>, <short commit>)" for the source list.
        described["display_label"] = display_label(dict(row.scope or {}))
        # The linked connection (ids only) and what agents may do on the repository through it.
        described["connection_id"] = row.connection_id
        if not row.connection_id:
            # The connections a picker offers for this unlinked repository (id, name, type; ``git_autolink.py``).
            described["connection_candidates"] = await connection_candidates(db, row.project_id, row.scope)
        described["access_mode"] = (row.scope or {}).get(ACCESS_MODE)
        # Whether the repository has its own Git token, when and by whom; never the token.
        described["git_token"] = await git_token_state(db, row.project_id, row.scope)
    if row.kind == CONNECTOR_KIND_JIRA:
        # off, active (with its project -> product mapping) or needs_configuration (no product).
        described["release_sync"] = release_sync_state(dict(row.scope or {}))
    entry = KINDS.get(row.kind)
    if entry is not None and entry.describe is not None:
        described |= await entry.describe(db, row)
    return described


async def list_connectors(db: AsyncSession, authorized: AuthorizedWorkspace) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(KnowledgeSourceConnector)
                .where(KnowledgeSourceConnector.project_id == authorized.project_id)
                .order_by(KnowledgeSourceConnector.connector_key)
                .limit(MAX_CONNECTORS_LISTED)
            )
        )
        .scalars()
        .all()
    )
    return [await describe_connector(db, row) for row in rows]
