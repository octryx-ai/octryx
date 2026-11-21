"""``connection`` problems from the connections themselves.

- **failing**: an active connection whose ``state`` is ``failing`` (a connection test, or a runtime use refused as
  unauthenticated, ``named_connections/runtime_state.py``) is a problem; the title is its ``state_reason``. Its
  Workspace is its owner (``owner_workspace_id``, a Workspace row's ``project_id``), else it is platform-wide.
- **unlinked**: a Knowledge source of a connection type without ``connection_id``, or a ticket intake without one or
  still naming ``default``, needs attention (``connection_unlinked``): it reads through the connector's entry until
  an admin links it. The fix opens the connections page. A Confluence source whose spaces the one resolver serves
  with several connections reads each space with its own connection (``confluence_multi.py``) and cannot be linked to
  one (every run would be refused, ``connection_pin_mismatch``): it is no problem.

Every problem names the connection it is about (``Problem.connection_id``) where there is one, so the connection page
counts it (``services/connections/problems_view.py``).
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection, WorkItemSyncConfig
from ...models.project.knowledge_source_sync import KnowledgeSourceConnector
from ..named_connections.contract import DEFAULT_CONNECTION_NAME
from ..named_connections.routes_model import NamedConnectionRoutes
from ..named_connections.workspace_routes import workspace_routes
from .links import TARGET_CONNECTION, fix_link
from .model import KIND_CONNECTION, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem, workspace_of

STATE_FAILING = "failing"
REASON_FAILING = "connection_failing"
REASON_UNLINKED = "connection_unlinked"
KNOWLEDGE_KINDS = ("confluence", "jira", "servicenow", "kubernetes")
PER_SPACE_KIND = "confluence"  # reads each scope item with its own connection
INTAKE_TYPES = ("jira", "servicenow")


async def _failing(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    row = ConnectorNamedConnection
    workspace = func.coalesce(row.owner_workspace_id, row.project_id, "")
    rows = (await db.execute(
        select(row).where(row.is_active.is_(True), row.state == STATE_FAILING, ctx.scope(workspace))
        .order_by(row.updated_at.desc()).limit(ctx.limit)
    )).scalars().all()
    return [Problem(
        kind=KIND_CONNECTION, severity=SEVERITY_PROBLEM, object_type="connection", object_id=item.id,
        object_name=item.name, reason_code=REASON_FAILING,
        title=f"{item.name}: {item.state_reason or 'the connection fails.'}",
        since=item.last_tested_at or item.updated_at, last_seen=item.updated_at,
        workspace_id=workspace_of(item.owner_workspace_id or item.project_id), connection_id=item.id,
        fix=fix_link(TARGET_CONNECTION, object_id=item.id),
    ) for item in rows]


async def _spanning(db: AsyncSession, sources: list[KnowledgeSourceConnector]) -> set[str]:
    """The Confluence sources whose spaces several connections serve in their Workspace (``routes.served_by``)."""
    from ..knowledge.sources.sync.scope_connections import scope_items

    routes: dict[str, NamedConnectionRoutes] = {}
    spanning: set[str] = set()
    for source in sources:
        if source.kind != PER_SPACE_KIND:
            continue
        if source.project_id not in routes:
            routes[source.project_id] = await workspace_routes(db, source.project_id, (PER_SPACE_KIND,),
                                                               secrets=False)
        keys = scope_items(PER_SPACE_KIND, dict(source.scope or {}))
        if len(routes[source.project_id].served_by(PER_SPACE_KIND, keys)) > 1:
            spanning.add(source.id)
    return spanning


async def _unlinked(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    sources = (await db.execute(
        select(KnowledgeSourceConnector).where(
            KnowledgeSourceConnector.connection_id.is_(None), KnowledgeSourceConnector.kind.in_(KNOWLEDGE_KINDS),
            ctx.scope(KnowledgeSourceConnector.project_id))
        .order_by(KnowledgeSourceConnector.connector_key).limit(ctx.limit)
    )).scalars().all()
    spanning = await _spanning(db, list(sources))
    intakes = (await db.execute(
        select(WorkItemSyncConfig).where(
            or_(WorkItemSyncConfig.connection_id.is_(None),
                WorkItemSyncConfig.connection_id == DEFAULT_CONNECTION_NAME),
            WorkItemSyncConfig.source_type.in_(INTAKE_TYPES), ctx.scope(WorkItemSyncConfig.project_id))
        .order_by(WorkItemSyncConfig.name).limit(ctx.limit)
    )).scalars().all()
    problems = [Problem(
        kind=KIND_CONNECTION, severity=SEVERITY_ATTENTION, object_type="knowledge_source", object_id=item.id,
        object_name=item.connector_key, reason_code=REASON_UNLINKED,
        title=f"Knowledge source {item.connector_key}: assign a connection.",
        since=item.created_at, last_seen=ctx.now, workspace_id=item.project_id, fix=fix_link(TARGET_CONNECTION),
    ) for item in sources if item.id not in spanning]
    problems += [Problem(
        kind=KIND_CONNECTION, severity=SEVERITY_ATTENTION, object_type="intake", object_id=item.id,
        object_name=item.name, reason_code=REASON_UNLINKED,
        title=f"Ticket intake {item.name}: assign a connection.",
        since=item.created_at, last_seen=ctx.now, workspace_id=item.project_id, fix=fix_link(TARGET_CONNECTION),
    ) for item in intakes]
    return problems


async def connection_problems(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    return [*await _failing(db, ctx), *await _unlinked(db, ctx)]


__all__ = ["REASON_FAILING", "REASON_UNLINKED", "connection_problems"]
