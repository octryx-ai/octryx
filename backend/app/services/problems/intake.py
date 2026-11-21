"""``intake`` problems: active ticket intakes (``work_item_sync_configs``) whose last sync did not complete.

``last_sync_status`` ``failed`` is a problem, ``blocked`` (refused by policy) needs attention. ``since``/``count``
are the ``work_item_sync_runs`` in that status after the last run in another state, inside the window; the title
names an ``error`` code of that series when the runs recorded one.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItemSyncConfig, WorkItemSyncRun
from .links import TARGET_INTAKE, fix_link
from .model import KIND_INTAKE, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem

STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
_REPORTED = (STATUS_FAILED, STATUS_BLOCKED)


async def _series(db: AsyncSession, ctx: CollectContext, config_ids: list[str]) -> dict[str, tuple]:
    """``config -> (first, last, count, error)`` of the failed or blocked runs after the last other run."""
    run = WorkItemSyncRun
    last_other = (select(run.sync_config_id, func.max(run.created_at).label("other_at"))
                  .where(run.sync_config_id.in_(config_ids), run.status.not_in(_REPORTED))
                  .group_by(run.sync_config_id).subquery())
    rows = (await db.execute(
        select(run.sync_config_id, func.min(run.created_at), func.max(run.created_at), func.count(),
               func.max(run.error))
        .outerjoin(last_other, last_other.c.sync_config_id == run.sync_config_id)
        .where(run.sync_config_id.in_(config_ids), run.status.in_(_REPORTED), run.created_at >= ctx.window_start,
               or_(last_other.c.other_at.is_(None), run.created_at > last_other.c.other_at))
        .group_by(run.sync_config_id)
    )).all()
    return {config_id: (first, last, count, error) for config_id, first, last, count, error in rows}


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    config = WorkItemSyncConfig
    rows = (await db.execute(
        select(config)
        .where(config.is_active.is_(True), config.last_sync_status.in_(_REPORTED), ctx.scope(config.project_id))
        .order_by(config.last_sync_at.desc()).limit(ctx.limit)
    )).scalars().all()
    series = await _series(db, ctx, [item.id for item in rows]) if rows else {}
    problems = []
    for item in rows:
        failed = item.last_sync_status == STATUS_FAILED
        first, last, count, error = series.get(item.id, (None, None, 0, None))
        problems.append(Problem(
            kind=KIND_INTAKE, severity=SEVERITY_PROBLEM if failed else SEVERITY_ATTENTION,
            object_type="intake", object_id=item.id, object_name=item.name,
            reason_code=item.last_sync_status,
            title=(f"Ticket intake {item.name}: the last sync failed"
                   + (f" ({str(error).replace('_', ' ')})." if error else ".")
                   if failed else f"Ticket intake {item.name}: the last sync was blocked by policy."),
            since=first or item.last_sync_at, last_seen=last or item.last_sync_at, count=max(int(count or 0), 1),
            workspace_id=item.project_id, fix=fix_link(TARGET_INTAKE, workspace_id=item.project_id),
            connection_id=item.connection_id if item.connection_id != "default" else None,
        ))
    return problems


__all__ = ["STATUS_BLOCKED", "STATUS_FAILED", "collect"]
