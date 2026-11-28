"""Run one Source Sync connector now (``run_connector``), or record why it cannot run."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KIND_JIRA,
    CONNECTOR_STATE_PAUSED,
    RUN_STATE_FAILED,
    RUN_STATE_NEEDS_CONFIGURATION,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from .....time_utils import utc_now
from ....named_connections.runtime_state import record_runtime_failure
from ....project_activity import project_is_inactive
from ...access.authorization import AuthorizedWorkspace
from ...runtime import EvidenceRuntime
from .confluence_multi import multi_connection_connector
from .connections import SourceConnection
from .contract import (
    REASON_CONNECTOR_PAUSED,
    REASON_PARSER_NOT_CONFIGURED,
    REASON_SCOPE_NOT_ALLOWED,
    REASON_SOURCE_UNAUTHORIZED,
    REASON_WORKSPACE_INACTIVE,
    ConnectorError,
    SourceConnector,
)
from .git_autolink import auto_link_connection, link_fields, record_auto_link
from .git_bitbucket import bind_repository_scope
from .git_config import carry_run_state
from .git_run import record_git_run
from .incremental import TRIGGER_MANUAL
from .jira_release_config import RELEASE_SYNC_OFF, release_sync_state
from .kinds import BuildRequest, connector_kind
from .runner import SyncRefusedError, run_source_sync
from .scope_connections import resolve_scope_connections, scope_allowed
from .stored_types import ReleaseSyncState

# The service's logger, so the run's log lines keep their origin.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".service")


def build_connector(connection: SourceConnection, row: KnowledgeSourceConnector, *, transport=None, db=None,
                    actor_id: str | None = None) -> SourceConnector:
    # An unregistered kind is refused, never read as Jira.
    entry = connector_kind(row.kind)
    return entry.build(BuildRequest(connection=connection, row=row, transport=transport, db=db, actor_id=actor_id))


async def _repair_unlinked(db: AsyncSession, row: KnowledgeSourceConnector, actor_id: str | None) -> None:
    scope = dict(row.scope or {})
    connection_id = await auto_link_connection(db, row.project_id, scope)
    if connection_id is None:
        return
    bound = await bind_repository_scope(db, row.project_id, connection_id, link_fields(scope), scope)
    row.scope = carry_run_state(scope, bound)
    row.connection_id = connection_id
    record_auto_link(db, actor_id=actor_id or row.schedule_owner_id or row.created_by, project_id=row.project_id,
                     connector_id=row.id, connector_key=row.connector_key, connection_id=connection_id,
                     scope=dict(row.scope))
    await db.flush()


async def _refused_run(
    db: AsyncSession, row: KnowledgeSourceConnector, reason: str, actor_id: str | None
) -> KnowledgeSourceSyncRun:
    now = utc_now()
    run = KnowledgeSourceSyncRun(
        connector_id=row.id,
        project_id=row.project_id,
        state=RUN_STATE_NEEDS_CONFIGURATION,
        reason=reason,
        report={},
        outcomes=[],
        triggered_by=actor_id,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    await db.flush()
    row.last_run_id = run.id
    await db.commit()
    return run


async def run_connector(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    row: KnowledgeSourceConnector,
    actor_id: str | None,
    transport=None,
    trigger: str = TRIGGER_MANUAL,
    pin: Callable[[Any], str] | None = None,
) -> KnowledgeSourceSyncRun:
    if await project_is_inactive(db, row.project_id):
        raise SyncRefusedError(REASON_WORKSPACE_INACTIVE)
    if row.state == CONNECTOR_STATE_PAUSED:
        raise SyncRefusedError(REASON_CONNECTOR_PAUSED)
    resolved = await _resolved_scope(db, row, actor_id, pin)
    if isinstance(resolved, KnowledgeSourceSyncRun):
        return resolved
    scope, scoped = resolved
    if scoped.named:
        # Which connection reads which scope item; names, ids and keys only, never a URL or credential.
        logger.info(
            "Knowledge source sync connections: connector=%s scopes=%s", row.connector_key, scoped.described()
        )
    if scoped.single is not None:
        connector = build_connector(scoped.single, row, transport=transport, db=db, actor_id=actor_id)
    else:
        connector = multi_connection_connector(scope, scoped, transport=transport)
    if connector.requires_parser and runtime.parser is None:
        return await _refused_run(db, row, REASON_PARSER_NOT_CONFIGURED, actor_id)
    release = release_sync_state(scope) if row.kind == CONNECTOR_KIND_JIRA else None
    run = await run_source_sync(
        db,
        runtime=runtime,
        authorized=authorized,
        connector_row=row,
        connector=connector,
        actor_id=actor_id,
        trigger=trigger,
    )
    await _after_run(db, row, run, connector, release)
    return run


async def _resolved_scope(
    db: AsyncSession, row: KnowledgeSourceConnector, actor_id: str | None, pin: Callable[[Any], str] | None
):
    try:
        connector_kind(row.kind)
    except ConnectorError as error:
        return await _refused_run(db, row, error.reason, actor_id)
    try:
        if row.kind == CONNECTOR_KIND_GIT_REPOSITORY and not row.connection_id:
            await _repair_unlinked(db, row, actor_id)
        scope = dict(row.scope or {})
        scoped = await resolve_scope_connections(db, kind=row.kind, project_id=row.project_id, scope=scope,
                                                 connection_id=row.connection_id)
    except ConnectorError as error:
        return await _refused_run(db, row, error.reason, actor_id)
    if not scope_allowed(row.kind, scope, scoped):
        return await _refused_run(db, row, REASON_SCOPE_NOT_ALLOWED, actor_id)
    if pin is not None and (pinned := pin(scoped)):
        return await _refused_run(db, row, pinned[:40], actor_id)
    return scope, scoped


async def _after_run(
    db: AsyncSession, row: KnowledgeSourceConnector, run: KnowledgeSourceSyncRun, connector: SourceConnector,
    release: ReleaseSyncState | None,
) -> None:
    if row.kind == CONNECTOR_KIND_GIT_REPOSITORY:
        await record_git_run(db, connector_id=row.id, run=run, connector=connector)
    if run.state == RUN_STATE_FAILED and run.reason == REASON_SOURCE_UNAUTHORIZED and row.connection_id:
        # The linked connection shows failing, on its page and in the problems list.
        if await record_runtime_failure(db, row.connection_id, "knowledge"):
            await db.commit()
    if release is not None and release["state"] != RELEASE_SYNC_OFF:
        # The run report says whether this run synced releases, or why not (needs_configuration).
        run.report = {**dict(run.report or {}), "release_sync": release}
        await db.commit()
