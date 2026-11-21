"""The connection a Work item's own reads and write-backs use (Jira transitions/comments, ServiceNow work notes).

Never the project config keys (``jira_url``, ``servicenow_url`` of the merged project config): the item is served by
the tool router's plan for its binding key (``named_connections.service_config``): its Jira project or its
ServiceNow table. An item that came in through an intake naming a connection (``WorkItemSyncConfig.connection_id``)
names that connection explicitly, so the write-back goes back through the account that read it; a connection that
no longer serves the key is refused (``connection_scope_mismatch``), never replaced by another one.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem, WorkItemSyncConfig
from ..named_connections.service_config import ConnectionRefusalError, service_connection_config

logger = logging.getLogger(__name__)


class UnknownItemSourceError(ValueError):
    """The connector names no registered Work source: there is no binding key to give, so none is guessed."""


def item_scope_key(item: WorkItem, connector: str) -> str:
    """The binding key of the item, as its source defines it (``intake/registry``): the Jira project of its issue
    key, the ServiceNow table of its record, ...

    An unknown connector is refused (:class:`UnknownItemSourceError`) rather than falling
    through to the ServiceNow table, where a third source's write-back would be bound to a ServiceNow key."""
    from .intake.registry import source_for

    source = source_for(connector)
    if source is None:
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
    """``(config, None)`` of the connection serving the item, or ``({}, refusal code)`` when none may."""
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
