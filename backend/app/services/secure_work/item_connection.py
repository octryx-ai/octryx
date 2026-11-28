"""The connection a Work item's own reads and write-backs use (Jira transitions/comments, ServiceNow work notes)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem, WorkItemSyncConfig
from ..named_connections.service_config import ConnectionRefusalError, service_connection_config

logger = logging.getLogger(__name__)


class UnknownItemSourceError(ValueError):
    # There is no binding key to give, so none is guessed.
    pass


def item_scope_key(item: WorkItem, connector: str) -> str:
    from .intake.registry import source_for

    source = source_for(connector)
    if source is None:
        # Never the ServiceNow fallback: a third source's write-back would be bound to a ServiceNow table
        raise UnknownItemSourceError(f"no Work source {connector!r}")
    return source.scope_key(item)


async def _intake_connection(db: AsyncSession, item: WorkItem) -> str | None:
    if not item.sync_config_id:
        return None
    row = await db.get(WorkItemSyncConfig, item.sync_config_id)
    return str(row.connection_id) if row is not None and row.connection_id else None


async def work_item_connection_config(
    db: AsyncSession, item: WorkItem, connector: str
) -> tuple[dict[str, Any], str | None]:
    try:
        key = item_scope_key(item, connector)
    except UnknownItemSourceError:
        return {}, "source_unknown"
    try:
        served = await service_connection_config(
            db, item.project_id, connector, keys=(key,) if key else (),
            explicit_connection=await _intake_connection(db, item),
        )
    except ConnectionRefusalError as refused:
        logger.warning("Work item connection refused: connector=%s item=%s code=%s", connector, item.id, refused.code)
        return {}, refused.code
    return served.config, None


__all__ = ["UnknownItemSourceError", "item_scope_key", "work_item_connection_config"]
