"""A Knowledge source linked to a connection (``knowledge_source_connectors.connection_id``). A scope item resolving to
another connection refuses the run."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.named_connections.workspace_routes import workspace_routes

from .....models import ConnectorNamedConnection
from ....named_connections.grants import grant_for
from ....named_connections.linked_use import (
    USE_KNOWLEDGE,
    LinkedConnectionRefusedError,
    deviation_refusal,
    resolve_linked,
)
from .contract import (
    REASON_CONNECTION_DISABLED,
    REASON_CONNECTION_NOT_AVAILABLE,
    REASON_CONNECTION_PIN_UNKNOWN,
    ConnectorError,
)


async def linked_scope(db: AsyncSession, *, kind: str, project_id: str, scope: dict, connection_id: str,
                       items: tuple[str, ...]) -> dict:
    routes = await workspace_routes(db, project_id, (kind,), secrets=False)
    try:
        linked = await resolve_linked(db, project_id, kind, connection_id, routes)
    except LinkedConnectionRefusedError as error:
        raise ConnectorError(error.code) from None
    if linked is None:
        raise ConnectorError(REASON_CONNECTION_PIN_UNKNOWN)
    refused = deviation_refusal(linked.grant, USE_KNOWLEDGE, kind, items)
    if refused is not None:
        raise ConnectorError(refused.code)
    return {**scope, "connection_id": linked.ref}


async def check_linked_grant(db: AsyncSession, *, project_id: str, connection_id: str) -> None:
    row = await db.get(ConnectorNamedConnection, connection_id)
    if row is None:
        raise ConnectorError(REASON_CONNECTION_PIN_UNKNOWN)
    grant = await grant_for(db, row, project_id)
    if grant is None:
        raise ConnectorError(REASON_CONNECTION_NOT_AVAILABLE)
    if not grant.is_active:
        raise ConnectorError(REASON_CONNECTION_DISABLED)
    refused = deviation_refusal(grant, USE_KNOWLEDGE, str(row.tool_name), ())
    if refused is not None:
        raise ConnectorError(refused.code)


__all__ = ["check_linked_grant", "linked_scope"]
