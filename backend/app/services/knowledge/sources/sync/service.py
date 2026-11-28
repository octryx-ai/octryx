"""Configure, list and run the Source Sync connectors of one Workspace."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models import AuditLog
from .....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from .....time_utils import utc_now
from ....project_activity import project_is_inactive
from ...access.authorization import AuthorizedWorkspace
from ...ledger.errors import EvidenceLedgerContractError, EvidenceRecordNotFoundError, InvalidEvidenceRequestError
from ..repository_git_token import check_git_token, source_repository, store_git_token
from .config import ConnectorConfig
from .contract import REASON_SCOPE_NOT_ALLOWED, REASON_WORKSPACE_INACTIVE, ConnectorError
from .cursor import SyncCursor
from .git_autolink import auto_link_connection, link_fields, record_auto_link
from .git_bitbucket import bind_repository_scope
from .git_config import ACCESS_MODE, carry_run_state, configuration_of, validate_access_mode
from .owner_rules import enforce_source_rules
from .scope_connections import require_known_pin, resolve_scope_connections, scope_allowed

CONFIGURE_AUDIT_ACTION = "knowledge.connector.configure"
ACCESS_MODE_AUDIT_ACTION = "knowledge.connector.access_mode"


async def get_connector(
    db: AsyncSession, authorized: AuthorizedWorkspace, connector_key: str
) -> KnowledgeSourceConnector:
    row = (
        await db.execute(
            select(KnowledgeSourceConnector).where(
                KnowledgeSourceConnector.project_id == authorized.project_id,
                KnowledgeSourceConnector.connector_key == connector_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise EvidenceRecordNotFoundError()
    return row


async def configure_connector(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, config: ConnectorConfig, actor_id: str,
    git_token: str | None = None,
) -> KnowledgeSourceConnector:
    # The Git token is checked against exactly that repository before anything is saved.
    if type(authorized) is not AuthorizedWorkspace or not authorized.may_author:
        raise EvidenceLedgerContractError()
    if await project_is_inactive(db, authorized.project_id):
        raise ConnectorError(REASON_WORKSPACE_INACTIVE)
    # One rule for every source type (``owner_rules``): a granted connection, ``workspace`` visibility admin only.
    await enforce_source_rules(db, project_id=authorized.project_id, config=config, actor_id=actor_id)
    try:
        existing: KnowledgeSourceConnector | None = await get_connector(db, authorized, config.connector_key)
    except EvidenceRecordNotFoundError:
        existing = None
    config, link, auto_linked = await _link_repository(db, authorized, config, existing)
    await require_known_pin(db, kind=config.kind, project_id=authorized.project_id, scope=config.scope)
    scoped = await resolve_scope_connections(db, kind=config.kind, project_id=authorized.project_id, scope=config.scope,
                                             connection_id=link)
    if not scope_allowed(config.kind, config.scope, scoped):
        raise ConnectorError(REASON_SCOPE_NOT_ALLOWED)
    checked = None
    if git_token is not None:
        checked = await check_git_token(source_repository(config.scope) if link else None, git_token)
    row = _connector_row(db, authorized, config, existing, actor_id)
    scope = _apply_config(row, config, actor_id)
    await db.flush()
    db.add(_configure_audit(authorized, config, row, actor_id))
    if auto_linked is not None:
        record_auto_link(db, actor_id=actor_id, project_id=authorized.project_id, connector_id=row.id,
                         connector_key=config.connector_key, connection_id=auto_linked, scope=scope)
    if checked is not None:
        await store_git_token(db, connector=row, checked=checked, actor_id=actor_id)
    await db.commit()
    return row


async def _link_repository(
    db: AsyncSession, authorized: AuthorizedWorkspace, config: ConnectorConfig,
    existing: KnowledgeSourceConnector | None,
) -> tuple[ConnectorConfig, str | None, str | None]:
    link = auto_linked = None
    if (config.kind == CONNECTOR_KIND_GIT_REPOSITORY and not config.connection_id
            and (existing is None or not existing.connection_id)):
        # No connection chosen (the repository forms have no picker): the one usable connection that reads this
        # repository is linked; several are refused with their list (``git_autolink.py``).
        auto_linked = await auto_link_connection(db, authorized.project_id, config.scope)
        if auto_linked is not None:
            config = replace(config, connection_id=auto_linked, git_fields=link_fields(config.scope), scope={})
    if config.kind == CONNECTOR_KIND_GIT_REPOSITORY and config.connection_id:
        # A repository read through its linked connection: checked against that connection's host here.
        scope = await bind_repository_scope(db, authorized.project_id, config.connection_id, config.git_fields or {},
                                            dict(existing.scope or {}) if existing is not None else None)
        config, link = replace(config, scope=scope, git_fields=None), config.connection_id
    return config, link, auto_linked


def _connector_row(
    db: AsyncSession, authorized: AuthorizedWorkspace, config: ConnectorConfig,
    existing: KnowledgeSourceConnector | None, actor_id: str,
) -> KnowledgeSourceConnector:
    if existing is not None:
        row = existing
    else:
        row = KnowledgeSourceConnector(
            project_id=authorized.project_id, connector_key=config.connector_key, kind=config.kind, created_by=actor_id
        )
        db.add(row)
    if row.kind != config.kind:
        raise InvalidEvidenceRequestError()
    return row


def _apply_config(row: KnowledgeSourceConnector, config: ConnectorConfig, actor_id: str) -> dict:
    if row.kind == CONNECTOR_KIND_GIT_REPOSITORY and config.connection_id:
        row.connection_id = config.connection_id
    scope = dict(config.scope)
    if row.kind == CONNECTOR_KIND_GIT_REPOSITORY and row.scope:
        # ``head_commit``/``head_dirty`` are run state: carried over, never a configuration change.
        scope = carry_run_state(dict(row.scope), scope)
    if row.scope and configuration_of(dict(row.scope)) != configuration_of(scope):
        # Offsets of an open pass belong to the old scope: the next run starts a new pass. The pass
        # number keeps counting, so items of earlier passes are still recognised as unseen.
        cursor = SyncCursor.load(row.cursor)
        row.cursor = SyncCursor(
            pass_number=cursor.pass_number,
            completed_passes=cursor.completed_passes,
            last_completed_at=cursor.last_completed_at,
        ).as_dict()
    row.scope = scope
    row.products = list(config.products)
    row.version = config.version
    row.max_items_per_run = config.max_items_per_run
    row.state = config.state
    row.cursor = row.cursor or {}
    _apply_schedule(row, config, actor_id)
    return scope


def _configure_audit(
    authorized: AuthorizedWorkspace, config: ConnectorConfig, row: KnowledgeSourceConnector, actor_id: str
) -> AuditLog:
    return AuditLog(
        user_id=actor_id,
        action=CONFIGURE_AUDIT_ACTION,
        resource_type="knowledge_source_connector",
        resource_id=row.id,
        project_id=row.project_id,
        details={
            "workspace_id": authorized.project_id,
            "connector_key": config.connector_key,
            "kind": config.kind,
            "scope": config.scope,
            "products": list(config.products),
            "version": config.version,
            "state": config.state,
            "schedule_enabled": config.schedule_enabled,
            "schedule_interval_minutes": config.schedule_interval_minutes,
            **({"connection_id": config.connection_id} if config.connection_id else {}),
        },
    )


async def set_access_mode(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, row: KnowledgeSourceConnector, access_mode: object,
    actor_id: str,
) -> KnowledgeSourceConnector:
    if type(authorized) is not AuthorizedWorkspace or not authorized.may_author:
        raise EvidenceLedgerContractError()
    mode = validate_access_mode(access_mode)
    scope = dict(row.scope or {})
    if row.kind != CONNECTOR_KIND_GIT_REPOSITORY or not row.connection_id or ACCESS_MODE not in scope:
        raise ConnectorError(REASON_SCOPE_NOT_ALLOWED)
    before = scope[ACCESS_MODE]
    row.scope = {**scope, ACCESS_MODE: mode}
    db.add(
        AuditLog(
            user_id=actor_id,
            action=ACCESS_MODE_AUDIT_ACTION,
            resource_type="knowledge_source_connector",
            resource_id=row.id,
            project_id=row.project_id,
            details={"workspace_id": authorized.project_id, "connector_key": row.connector_key,
                     "connection_id": row.connection_id, "before": before, "after": mode},
        )
    )
    await db.commit()
    return row


def _apply_schedule(row: KnowledgeSourceConnector, config: ConnectorConfig, actor_id: str) -> None:
    if not config.schedule_enabled:
        row.schedule_enabled, row.schedule_owner_id, row.next_scheduled_at = False, None, None
    else:
        if not row.schedule_enabled or row.next_scheduled_at is None:
            row.next_scheduled_at = utc_now()
        else:
            # A shorter interval takes effect now rather than after the old, longer wait.
            earliest = utc_now() + timedelta(minutes=config.schedule_interval_minutes)
            row.next_scheduled_at = min(row.next_scheduled_at, earliest)
        row.schedule_enabled, row.schedule_owner_id = True, actor_id
    row.schedule_interval_minutes = config.schedule_interval_minutes



__all__ = [
    "ACCESS_MODE_AUDIT_ACTION",
    "CONFIGURE_AUDIT_ACTION",
    "configure_connector",
    "get_connector",
    "set_access_mode",
]
