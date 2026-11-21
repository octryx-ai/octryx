"""``connection`` problems: failing connector checks and unhealthy model providers.

- ``connector_health``: ``error``/``failed`` is a problem, ``degraded``/``warning`` needs attention; ``ok``,
  ``no_test``, ``unknown`` and ``disabled`` are not problems. A row whose last check is older than the window is
  stale (unknown on the health page) and is left out. ``since``/``count`` are the current failure series in
  ``connector_health_log``: the bad checks after the last good one, inside the window (one grouped query).
- ``llm_providers``: an active provider whose ``health_status`` is in the readiness vocabulary's unavailable set is
  a problem, in its degraded set needs attention (``services/provider/readiness``); last check inside the window.
  A provider without a Workspace is platform-wide (``workspace: null``, platform admins only).
- connections (``connection_rows.py``): a failing connection and a use without a linked connection.
"""

from __future__ import annotations

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorHealth, ConnectorHealthLog, LLMProvider
from .connection_rows import connection_problems
from .links import TARGET_CONNECTION, TARGET_PROVIDER, fix_link
from .model import (
    KIND_CONNECTION,
    SEVERITY_ATTENTION,
    SEVERITY_PROBLEM,
    CollectContext,
    Problem,
    scoped_object_id,
    workspace_of,
)

CONNECTOR_FAILING = ("error", "failed")
CONNECTOR_DEGRADED = ("degraded", "warning")
_BAD = CONNECTOR_FAILING + CONNECTOR_DEGRADED
PROVIDER_UNAVAILABLE = ("auth_denied", "error", "failed", "model_sync_failed", "provider_unavailable", "stopped",
                        "unavailable", "validation_failed")
PROVIDER_DEGRADED = ("no_models", "stale_cache")


async def _series(db: AsyncSession, ctx: CollectContext, names: list[str]) -> dict[tuple[str, str], tuple]:
    """``(connector, workspace) -> (first, last, count)`` of the bad checks after the last good one."""
    log = ConnectorHealthLog
    last_good = (select(log.connector_name, log.project_id, func.max(log.checked_at).label("good_at"))
                 .where(log.connector_name.in_(names), log.checked_at >= ctx.window_start, log.status.not_in(_BAD))
                 .group_by(log.connector_name, log.project_id).subquery())
    rows = (await db.execute(
        select(log.connector_name, log.project_id, func.min(log.checked_at), func.max(log.checked_at), func.count())
        .outerjoin(last_good, and_(last_good.c.connector_name == log.connector_name,
                                   last_good.c.project_id == log.project_id))
        .where(log.connector_name.in_(names), log.checked_at >= ctx.window_start, log.status.in_(_BAD),
               or_(last_good.c.good_at.is_(None), log.checked_at > last_good.c.good_at))
        .group_by(log.connector_name, log.project_id)
    )).all()
    return {(name, project or ""): (first, last, count) for name, project, first, last, count in rows}


async def _connector_problems(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    rows = (await db.execute(
        select(ConnectorHealth)
        .where(ConnectorHealth.status.in_(_BAD), ConnectorHealth.last_checked >= ctx.window_start,
               ctx.scope(ConnectorHealth.project_id))
        .order_by(ConnectorHealth.last_checked.desc()).limit(ctx.limit)
    )).scalars().all()
    series = await _series(db, ctx, sorted({row.connector_name for row in rows})) if rows else {}
    problems = []
    for row in rows:
        failing = row.status in CONNECTOR_FAILING
        workspace_id = workspace_of(row.project_id)
        first, last, count = series.get((row.connector_name, row.project_id or ""), (None, None, 0))
        problems.append(Problem(
            kind=KIND_CONNECTION, severity=SEVERITY_PROBLEM if failing else SEVERITY_ATTENTION,
            object_type="connection", object_id=row.connector_name, object_name=row.connector_name,
            key_object_id=scoped_object_id(row.connector_name, workspace_id),
            reason_code="check_failed" if failing else "degraded",
            title=(f"{row.connector_name}: the connection check fails." if failing
                   else f"{row.connector_name}: the connection is degraded."),
            since=first or row.last_checked, last_seen=last or row.last_checked, count=max(int(count or 0), 1),
            workspace_id=workspace_id,
            fix=fix_link(TARGET_CONNECTION, workspace_id=workspace_id),
        ))
    return problems


async def _provider_problems(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    workspace_column = case((LLMProvider.is_global.is_(True), ""), else_=func.coalesce(LLMProvider.project_id, ""))
    rows = (await db.execute(
        select(LLMProvider)
        .where(LLMProvider.is_active.is_(True), LLMProvider.health_status.in_(PROVIDER_UNAVAILABLE + PROVIDER_DEGRADED),
               LLMProvider.last_health_check_at >= ctx.window_start, ctx.scope(workspace_column))
        .order_by(LLMProvider.last_health_check_at.desc()).limit(ctx.limit)
    )).scalars().all()
    problems = []
    for provider in rows:
        unavailable = provider.health_status in PROVIDER_UNAVAILABLE
        name = provider.display_name or provider.name
        workspace_id = None if provider.is_global else workspace_of(provider.project_id)
        problems.append(Problem(
            kind=KIND_CONNECTION, severity=SEVERITY_PROBLEM if unavailable else SEVERITY_ATTENTION,
            object_type="provider", object_id=provider.id, object_name=name,
            reason_code=f"provider_{provider.health_status}",
            title=(f"{name}: the model provider is unavailable ({provider.health_status.replace('_', ' ')})."
                   if unavailable else f"{name}: the model provider is degraded "
                                       f"({provider.health_status.replace('_', ' ')})."),
            since=provider.last_health_check_at, last_seen=provider.last_health_check_at,
            workspace_id=workspace_id, fix=fix_link(TARGET_PROVIDER, object_id=provider.id),
        ))
    return problems


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    return [*await _connector_problems(db, ctx), *await _provider_problems(db, ctx),
            *await connection_problems(db, ctx)]


__all__ = ["CONNECTOR_DEGRADED", "CONNECTOR_FAILING", "PROVIDER_DEGRADED", "PROVIDER_UNAVAILABLE", "collect"]
