"""``sync`` problems: knowledge source connectors whose sync fails or whose schedule is overdue.

- The latest ``knowledge_source_sync_runs`` row per connector decides: ``failed`` is a problem (reason: the run's
  ``reason``), ``needs_configuration`` needs attention. ``since``/``count`` are the failed runs after the last
  run in another state, inside the window.
- A connector with ``schedule_enabled`` and state ``active`` whose ``next_scheduled_at`` lies more than two
  intervals in the past needs attention (``overdue``): its schedule is not running.
- An active connector without a running schedule whose last completed sync is older than :data:`STALE_AFTER`
  (or that never completed one and exists that long) needs attention (``stale``): nothing fails, but the
  knowledge is old. A connector whose latest run failed is reported as failed, not also as stale.
- A ``git_repository`` source in ``local_snapshot`` mode records no sync run: the launcher uploads it. It is stale
  when its last upload (the snapshot pass the upload completed, ``cursor``; else the source's ``updated_at``) is
  older than :data:`STALE_AFTER`, and the fix is a new upload, not a sync or a schedule.
- A source is named as Knowledge › Sources names it (a repository by ``<name> (<version>, <commit>)``, else its key),
  and a title carries no date: the row's "Since" shows it in the reader's format.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import KnowledgeSourceConnector, KnowledgeSourceSyncRun
from ...models.project.knowledge_source_sync import (
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_STATE_ACTIVE,
    RUN_STATE_COMPLETED,
    RUN_STATE_FAILED,
    RUN_STATE_NEEDS_CONFIGURATION,
)
from ...time_utils import ensure_utc
from ..knowledge.sources.repository_snapshot.labels import display_label
from ..knowledge.sources.sync.git_config import FETCH_LOCAL_SNAPSHOT
from .links import TARGET_KNOWLEDGE_SOURCE, fix_link
from .model import KIND_SYNC, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem

OVERDUE_INTERVALS = 2
STALE_AFTER = timedelta(days=14)
_REPORTED = (RUN_STATE_FAILED, RUN_STATE_NEEDS_CONFIGURATION)


def source_name(connector: KnowledgeSourceConnector) -> str:
    """The source as Knowledge › Sources lists it: a repository by its display label, any other by its key."""
    if connector.kind == CONNECTOR_KIND_GIT_REPOSITORY and isinstance(connector.scope, dict):
        return display_label(connector.scope)
    return connector.connector_key


async def _failure_series(db: AsyncSession, ctx: CollectContext, connector_ids: list[str]) -> dict[str, tuple]:
    run = KnowledgeSourceSyncRun
    last_other = (select(run.connector_id, func.max(run.started_at).label("other_at"))
                  .where(run.connector_id.in_(connector_ids), run.state != RUN_STATE_FAILED)
                  .group_by(run.connector_id).subquery())
    rows = (await db.execute(
        select(run.connector_id, func.min(run.started_at), func.count())
        .outerjoin(last_other, last_other.c.connector_id == run.connector_id)
        .where(run.connector_id.in_(connector_ids), run.state == RUN_STATE_FAILED, run.started_at >= ctx.window_start,
               or_(last_other.c.other_at.is_(None), run.started_at > last_other.c.other_at))
        .group_by(run.connector_id)
    )).all()
    return {connector_id: (first, count) for connector_id, first, count in rows}


async def _failed_runs(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    run = KnowledgeSourceSyncRun
    latest = (select(run.connector_id, func.max(run.started_at).label("last"))
              .where(ctx.scope(run.project_id)).group_by(run.connector_id).subquery())
    rows = (await db.execute(
        select(run, KnowledgeSourceConnector)
        .join(latest, and_(latest.c.connector_id == run.connector_id, latest.c.last == run.started_at))
        .join(KnowledgeSourceConnector, KnowledgeSourceConnector.id == run.connector_id)
        .where(run.state.in_(_REPORTED))
        .order_by(run.started_at.desc()).limit(ctx.limit)
    )).all()
    failed_ids = sorted({item.connector_id for item, _ in rows if item.state == RUN_STATE_FAILED})
    series = await _failure_series(db, ctx, failed_ids) if failed_ids else {}
    problems = []
    for item, connector in rows:
        failed = item.state == RUN_STATE_FAILED
        reason = str(item.reason or item.state)
        first, count = series.get(item.connector_id, (None, 0))
        name = source_name(connector)
        problems.append(Problem(
            kind=KIND_SYNC, severity=SEVERITY_PROBLEM if failed else SEVERITY_ATTENTION,
            object_type="knowledge_source", object_id=connector.id, object_name=name,
            reason_code=reason if failed else RUN_STATE_NEEDS_CONFIGURATION,
            title=(f"Knowledge source {name}: the last sync failed ({reason.replace('_', ' ')})."
                   if failed else f"Knowledge source {name}: the sync needs configuration."),
            since=first or item.started_at, last_seen=item.finished_at or item.started_at,
            count=max(int(count or 0), 1), workspace_id=connector.project_id, connection_id=connector.connection_id,
            fix=fix_link(TARGET_KNOWLEDGE_SOURCE, workspace_id=connector.project_id,
                         object_id=connector.connector_key),
        ))
    return problems


async def _overdue_schedules(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    connector = KnowledgeSourceConnector
    rows = (await db.execute(
        select(connector)
        .where(connector.schedule_enabled.is_(True), connector.state == CONNECTOR_STATE_ACTIVE,
               connector.next_scheduled_at < ctx.now, ctx.scope(connector.project_id))
        .order_by(connector.next_scheduled_at.asc()).limit(ctx.limit)
    )).scalars().all()
    problems = []
    for item in rows:
        interval = timedelta(minutes=max(int(item.schedule_interval_minutes or 0), 1))
        if ctx.now - item.next_scheduled_at <= OVERDUE_INTERVALS * interval:
            continue
        problems.append(Problem(
            kind=KIND_SYNC, severity=SEVERITY_ATTENTION, object_type="knowledge_source", object_id=item.id,
            object_name=source_name(item), reason_code="overdue",
            title=f"Knowledge source {source_name(item)}: the scheduled sync is overdue.",
            since=item.next_scheduled_at, last_seen=ctx.now, workspace_id=item.project_id,
            connection_id=item.connection_id,
            fix=fix_link(TARGET_KNOWLEDGE_SOURCE, workspace_id=item.project_id, object_id=item.connector_key),
        ))
    return problems


def _is_snapshot(connector: KnowledgeSourceConnector) -> bool:
    scope = connector.scope if isinstance(connector.scope, dict) else {}
    return connector.kind == CONNECTOR_KIND_GIT_REPOSITORY and scope.get("fetch_mode") == FETCH_LOCAL_SNAPSHOT


def _uploaded_at(connector: KnowledgeSourceConnector) -> datetime | None:
    """When the last snapshot upload completed (naive UTC): its pass in the cursor, else ``updated_at``."""
    cursor = connector.cursor if isinstance(connector.cursor, dict) else {}
    for key in ("last_pass_closed_at", "last_completed_at"):
        try:
            return ensure_utc(datetime.fromisoformat(str(cursor[key]))).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
            continue
    return connector.updated_at


def _stale_snapshot(ctx: CollectContext, item: KnowledgeSourceConnector) -> Problem | None:
    uploaded = _uploaded_at(item)
    if uploaded is not None and uploaded >= ctx.now - STALE_AFTER:
        return None
    when = uploaded or item.created_at
    name = source_name(item)
    return Problem(
        kind=KIND_SYNC, severity=SEVERITY_ATTENTION, object_type="knowledge_source", object_id=item.id,
        object_name=name, reason_code="stale",
        title=(f"Knowledge source {name} was last uploaded more than {STALE_AFTER.days} days ago; upload a new "
               "snapshot from the launcher to refresh it."),
        since=when, last_seen=ctx.now, workspace_id=item.project_id,
        fix=fix_link(TARGET_KNOWLEDGE_SOURCE, workspace_id=item.project_id, object_id=item.connector_key),
    )


async def _stale_sources(db: AsyncSession, ctx: CollectContext, reported: set[str]) -> list[Problem]:
    connector, run = KnowledgeSourceConnector, KnowledgeSourceSyncRun
    completed = (select(run.connector_id, func.max(func.coalesce(run.finished_at, run.started_at)).label("done_at"))
                 .where(run.state == RUN_STATE_COMPLETED).group_by(run.connector_id).subquery())
    cutoff = ctx.now - STALE_AFTER
    rows = (await db.execute(
        select(connector, completed.c.done_at)
        .outerjoin(completed, completed.c.connector_id == connector.id)
        .where(connector.state == CONNECTOR_STATE_ACTIVE, connector.schedule_enabled.isnot(True),
               ctx.scope(connector.project_id),
               or_(completed.c.done_at < cutoff, and_(completed.c.done_at.is_(None), connector.created_at < cutoff)))
        .order_by(func.coalesce(completed.c.done_at, connector.created_at).asc()).limit(ctx.limit)
    )).all()
    problems = []
    for item, done_at in rows:
        if item.id in reported:
            continue
        if _is_snapshot(item):
            snapshot = _stale_snapshot(ctx, item)
            problems.extend([snapshot] if snapshot is not None else [])
            continue
        name = source_name(item)
        when = f"for more than {STALE_AFTER.days} days" if done_at else "yet"
        problems.append(Problem(
            kind=KIND_SYNC, severity=SEVERITY_ATTENTION, object_type="knowledge_source", object_id=item.id,
            object_name=name, reason_code="stale",
            title=f"Knowledge source {name} has not been synced {when} and has no schedule.",
            since=done_at or item.created_at, last_seen=ctx.now, workspace_id=item.project_id,
            fix=fix_link(TARGET_KNOWLEDGE_SOURCE, workspace_id=item.project_id, object_id=item.connector_key),
        ))
    return problems


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    failed = await _failed_runs(db, ctx)
    return [*failed, *await _overdue_schedules(db, ctx),
            *await _stale_sources(db, ctx, {item.object_id for item in failed})]


__all__ = ["OVERDUE_INTERVALS", "STALE_AFTER", "collect", "source_name"]
