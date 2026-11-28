"""Per-item sync state of one connector, and the tombstones it owes. Every function runs in the caller's transaction and
never commits."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import (
    ITEM_STATE_RETIRED,
    ITEM_STATE_WITHHELD,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
)
from ...ledger.errors import EvidenceLedgerContractError
from ...ledger.lifecycle import tombstone_source

MAX_EXTERNAL_ID_CHARS = 120
_EXTERNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


@dataclass(frozen=True, slots=True)
class ConnectorRef:
    id: str
    project_id: str
    kind: str
    connector_key: str
    products: tuple[str, ...]
    version: str | None
    max_items_per_run: int

    @classmethod
    def of(cls, row: KnowledgeSourceConnector) -> ConnectorRef:
        return cls(
            id=row.id,
            project_id=row.project_id,
            kind=row.kind,
            connector_key=row.connector_key,
            products=tuple(row.products or ()),
            version=row.version,
            max_items_per_run=int(row.max_items_per_run),
        )


def source_key_for(connector: ConnectorRef, external_id: str) -> str:
    # Connector-scoped, so two connectors never share a source.
    return source_key_of(connector.kind, connector.connector_key, external_id)


def source_key_of(kind: str, connector_key: str, external_id: str) -> str:
    if type(external_id) is not str or not _EXTERNAL_ID.fullmatch(external_id):
        raise EvidenceLedgerContractError()
    return f"{kind}.{connector_key}.{external_id.lower()}"


async def load_item(db: AsyncSession, connector: ConnectorRef, external_id: str) -> KnowledgeSourceSyncItem | None:
    return (
        await db.execute(
            select(KnowledgeSourceSyncItem).where(
                KnowledgeSourceSyncItem.connector_id == connector.id,
                KnowledgeSourceSyncItem.project_id == connector.project_id,
                KnowledgeSourceSyncItem.external_id == external_id,
            )
        )
    ).scalar_one_or_none()


def new_item(connector: ConnectorRef, external_id: str, *, state: str, outcome: str) -> KnowledgeSourceSyncItem:
    return KnowledgeSourceSyncItem(
        id=str(uuid.uuid4()),
        connector_id=connector.id,
        project_id=connector.project_id,
        external_id=external_id,
        source_key=source_key_for(connector, external_id),
        state=state,
        last_outcome=outcome,
        last_seen_pass=0,
    )


async def retire_item(db: AsyncSession, item: KnowledgeSourceSyncItem, *, withheld: bool, outcome: str) -> bool:
    retired = False
    if item.source_id is not None:
        await tombstone_source(db, project_id=item.project_id, source_id=item.source_id)
        retired = True
    item.source_id = None
    # Forget what was ingested, so the item is fetched and ingested again if it comes back.
    item.content_sha256 = None
    item.version_marker = None
    item.state = ITEM_STATE_WITHHELD if withheld else ITEM_STATE_RETIRED
    item.last_outcome = outcome
    return retired


async def served_items_unseen_in(
    db: AsyncSession, connector: ConnectorRef, pass_number: int
) -> list[KnowledgeSourceSyncItem]:
    return list(
        (
            await db.execute(
                select(KnowledgeSourceSyncItem)
                .where(
                    KnowledgeSourceSyncItem.connector_id == connector.id,
                    KnowledgeSourceSyncItem.project_id == connector.project_id,
                    KnowledgeSourceSyncItem.last_seen_pass < pass_number,
                    KnowledgeSourceSyncItem.source_id.is_not(None),
                )
                .order_by(KnowledgeSourceSyncItem.external_id)
            )
        )
        .scalars()
        .all()
    )


async def served_item_count(db: AsyncSession, row: KnowledgeSourceConnector) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeSourceSyncItem)
            .where(
                KnowledgeSourceSyncItem.connector_id == row.id,
                KnowledgeSourceSyncItem.project_id == row.project_id,
                KnowledgeSourceSyncItem.source_id.is_not(None),
            )
        )
        or 0
    )


async def connector_source_roles(db: AsyncSession, project_id: str, source_ids: list[str]) -> dict[str, str]:
    if not source_ids:
        return {}
    rows = await db.execute(
        select(KnowledgeSourceSyncItem.source_id, KnowledgeSourceSyncItem.document_role).where(
            KnowledgeSourceSyncItem.project_id == project_id,
            KnowledgeSourceSyncItem.source_id.in_(source_ids),
            KnowledgeSourceSyncItem.document_role.is_not(None),
        )
    )
    return {str(source_id): str(role) for source_id, role in rows.all()}


__all__ = [
    "ConnectorRef",
    "connector_source_roles",
    "load_item",
    "new_item",
    "retire_item",
    "served_items_unseen_in",
    "source_key_for",
    "source_key_of",
]
