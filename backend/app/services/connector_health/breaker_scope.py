"""Circuit breakers are keyed per connection scope, not per connector name.

A breaker keyed ``jira`` alone would let a failing platform connection (or a connector without a test) block
the Jira tools of every Workspace, including Workspaces with their own working connection. The key is
``<connector>@<scope>``:

* ``<connector>@platform`` — the platform connection; the health worker checks it and every
  Workspace that inherits it shares its breaker;
* ``<connector>@<project id>`` — a Workspace that sets its own connection identity
  (``tool_config.connection_fields.sets_connection_identity``) gets a breaker of its own.

Tool calls resolve the key for the run's Workspace (:func:`tool_call_breaker_key`), so a call
records success/failure against the same connection the health check tests.

A connector without a connection test reports ``no_test`` (``connector_test_service``): that is
not a failure, so it is recorded as health status ``no_test`` and never feeds a breaker.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

PLATFORM_SCOPE = "platform"
STATUS_NO_TEST = "no_test"


def connection_breaker_key(connector_name: str, project_id: str | None = None) -> str:
    return f"{connector_name}@{project_id or PLATFORM_SCOPE}"


async def _workspace_has_own_connection(db: AsyncSession, connector_name: str, project_id: str) -> bool:
    from ..tool_config import get_tool_config
    from ..tool_config.connection_fields import sets_connection_identity

    entry = await get_tool_config(db, connector_name, project_id)
    return entry is not None and bool(entry.is_active) and sets_connection_identity(connector_name, entry.config)


async def tool_call_breaker_key(db: AsyncSession, tool_name: str, context: Any) -> str | None:
    """The breaker key of the connection a tool call uses, or ``None`` for a non-connector tool."""
    from ..circuit_breaker import infer_connector_name

    connector_name = infer_connector_name(tool_name)
    if not connector_name:
        return None
    project_ids = list(getattr(context, "project_ids", None) or [])
    project_id = project_ids[0] if len(project_ids) == 1 else None
    if project_id and await _workspace_has_own_connection(db, connector_name, project_id):
        return connection_breaker_key(connector_name, project_id)
    return connection_breaker_key(connector_name)


def check_status(result: dict[str, Any]) -> str:
    """The health status of one connection check: ``ok``, ``error`` or ``no_test``."""
    if result.get("no_test"):
        return STATUS_NO_TEST
    return "ok" if result.get("ok") else "error"


async def record_platform_check(db: AsyncSession, connector_name: str, status: str, error: str) -> None:
    """Feed a check of the platform connection into that connection's breaker (never ``no_test``)."""
    from ..circuit_breaker import record_circuit_breaker_failure, record_circuit_breaker_success

    key = connection_breaker_key(connector_name)
    if status == "ok":
        await record_circuit_breaker_success(db, key)
    elif status == "error":
        await record_circuit_breaker_failure(db, key, error or "connector health check failed")


__all__ = [
    "PLATFORM_SCOPE",
    "STATUS_NO_TEST",
    "check_status",
    "connection_breaker_key",
    "record_platform_check",
    "tool_call_breaker_key",
]
