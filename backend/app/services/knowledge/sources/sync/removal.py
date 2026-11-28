"""End of a Source Sync connector: delete it, or deactivate every connector of a deleted Workspace. Synced ledger
sources are kept."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models import AuditLog
from .....models.project.knowledge_source_sync import (
    CONNECTOR_STATE_PAUSED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
    KnowledgeSourceSyncRun,
)
from .....time_utils import utc_now
from ...access.authorization import AuthorizedWorkspace
from ...ledger.errors import EvidenceLedgerContractError
from ..repository_git_token import remove_git_token_with_source
from .contract import REASON_RUN_IN_PROGRESS
from .runner import SyncRefusedError
from .service import get_connector

DELETE_AUDIT_ACTION = "knowledge.connector.delete"
DEACTIVATE_AUDIT_ACTION = "knowledge.connector.deactivate"
DEACTIVATE_REASON_PROJECT_DELETED = "project_deleted"
CONNECTOR_DELETED = "deleted"


def _stop_schedule(row: KnowledgeSourceConnector) -> None:
    row.schedule_enabled, row.schedule_owner_id, row.next_scheduled_at = False, None, None


async def delete_connector(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, connector_key: str, actor_id: str
) -> dict[str, Any]:
    if type(authorized) is not AuthorizedWorkspace or not authorized.may_author:
        raise EvidenceLedgerContractError()
    row = await get_connector(db, authorized, connector_key)
    if row.run_lease_until is not None and row.run_lease_until > utc_now():
        raise SyncRefusedError(REASON_RUN_IN_PROGRESS)
    _stop_schedule(row)
    retained_sources = (
        await db.execute(
            select(func.count(KnowledgeSourceSyncItem.id)).where(
                KnowledgeSourceSyncItem.connector_id == row.id, KnowledgeSourceSyncItem.source_id.is_not(None)
            )
        )
    ).scalar_one()
    # Children first: PostgreSQL enforces both foreign keys to the connector.
    removed_items = (
        await db.execute(delete(KnowledgeSourceSyncItem).where(KnowledgeSourceSyncItem.connector_id == row.id))
    ).rowcount
    removed_runs = (
        await db.execute(delete(KnowledgeSourceSyncRun).where(KnowledgeSourceSyncRun.connector_id == row.id))
    ).rowcount
    outcome = {
        "state": CONNECTOR_DELETED,
        "connector_key": row.connector_key,
        "kind": row.kind,
        "retained_sources": int(retained_sources or 0),
        "removed_sync_items": int(removed_items or 0),
        "removed_runs": int(removed_runs or 0),
    }
    db.add(
        AuditLog(
            user_id=actor_id,
            action=DELETE_AUDIT_ACTION,
            resource_type="knowledge_source_connector",
            resource_id=row.id,
            project_id=row.project_id,
            details={"workspace_id": authorized.project_id, **outcome},
        )
    )
    # The repository's own Git token goes with its last source in the Workspace (audited, secret destroyed).
    await remove_git_token_with_source(db, connector=row, actor_id=actor_id)
    await db.delete(row)
    await db.commit()
    return outcome


async def deactivate_workspace_connectors(db: AsyncSession, *, project_id: str, actor_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(KnowledgeSourceConnector)
            .where(KnowledgeSourceConnector.project_id == project_id)
            .order_by(KnowledgeSourceConnector.connector_key)
        )
    ).scalars().all()
    changed: list[str] = []
    for row in rows:
        if row.state == CONNECTOR_STATE_PAUSED and not row.schedule_enabled:
            continue
        previous = {"state": row.state, "schedule_enabled": bool(row.schedule_enabled)}
        row.state = CONNECTOR_STATE_PAUSED
        _stop_schedule(row)
        changed.append(row.id)
        db.add(
            AuditLog(
                user_id=actor_id,
                action=DEACTIVATE_AUDIT_ACTION,
                resource_type="knowledge_source_connector",
                resource_id=row.id,
                project_id=row.project_id,
                details={
                    "workspace_id": project_id,
                    "connector_key": row.connector_key,
                    "previous": previous,
                    "reason": DEACTIVATE_REASON_PROJECT_DELETED,
                },
            )
        )
    await db.flush()
    return changed


__all__ = [
    "CONNECTOR_DELETED",
    "DEACTIVATE_AUDIT_ACTION",
    "DELETE_AUDIT_ACTION",
    "deactivate_workspace_connectors",
    "delete_connector",
]
