"""The connection a platform service uses outside a tool call: the tool router's plan, not the raw config.

Lookups, write-backs, health checks and other platform services that talk to a connector themselves must not read
``jira_url`` / ``bitbucket_url`` / ``servicenow_url`` ... from the merged project config: in a Workspace served by
named connections those keys belong to the (possibly empty) default entry. They ask here instead, with the binding
keys their request concerns (a Jira project, a ServiceNow table, a ``project/repo``) and, where they know it, an
explicit connection id. The answer is exactly the plan ``tool_routing.routed_execute`` would run
(``route_planner.plan_connector``): a bound key → its connection, an unbound key → the default if its allowlist allows
it, no key → the default while it is usable, else the one usable candidate (several: ``connection_ambiguous``);
every refusal is raised as :class:`ConnectionRefusalError` with the router's code. Only the chosen connection's secrets
are resolved.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .descriptor import UnitIncompleteError
from .descriptors import descriptor_of
from .resolver import connection_config, connection_name, connection_ref, with_secrets
from .route_plan import RoutePlan, refusal, usable
from .route_planner import plan_connector, plan_route
from .routes_model import NAMED_CONNECTIONS_KEY, routes_of

REASON_CREDENTIAL_UNAVAILABLE = "named_connection_credential_unavailable"


class ConnectionRefusalError(Exception):
    """The router refused the connector use; ``code`` is the router's fixed reason, ``details`` its payload."""

    def __init__(self, details: dict[str, Any]) -> None:
        super().__init__(str(details.get("error") or details.get("code") or "connection refused"))
        self.code = str(details.get("code") or "")
        self.details = details


@dataclass(frozen=True, slots=True)
class ServiceConnection:
    """The effective config of the chosen connection (secrets resolved) and its identity (``default`` or an id)."""

    connection_id: str
    name: str
    config: dict[str, Any] = field(repr=False)


def _plain(base: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in base.items() if key != NAMED_CONNECTIONS_KEY}


async def _base(db: AsyncSession, project_id: str | None, base: dict[str, Any] | None) -> dict[str, Any]:
    if base is not None:
        return base
    from ..project.service import get_project_config

    return await get_project_config(project_id, db)


def _planned(connector: str, base: dict[str, Any], keys: Iterable[object], explicit: str | None) -> RoutePlan:
    plan = plan_connector(connector, base, keys=tuple(str(key) for key in keys if key),
                          explicit_connection=explicit)
    if plan.refusal is not None:
        raise ConnectionRefusalError(plan.refusal)
    if plan.fan_out or len(plan.targets) > 1:  # a service plan names no fan-out tool
        raise ConnectionRefusalError(refusal("connection_ambiguous", connector, "Several connections serve this use."))
    return plan


async def service_connection_config(
    db: AsyncSession,
    project_id: str | None,
    connector: str,
    *,
    keys: Iterable[object] = (),
    explicit_connection: str | None = None,
    base: dict[str, Any] | None = None,
) -> ServiceConnection:
    """The connection serving ``connector`` for ``keys`` in the Workspace (raises :class:`ConnectionRefusalError`)."""
    merged = await _base(db, project_id, base)
    plan = _planned(connector, merged, keys, explicit_connection)
    if plan.passthrough:
        return ServiceConnection(connection_ref(None), connection_name(None), _plain(merged))
    target = plan.targets[0]
    if target is not None:
        target = await with_secrets(db, target)
    config = connection_config(merged, connector, routes_of(merged), target)
    if target is not None and plan.descriptor is not None and plan.descriptor.runtime_guard is not None:
        try:
            plan.descriptor.runtime_guard(config)
        except UnitIncompleteError as incomplete:
            raise ConnectionRefusalError(refusal(
                REASON_CREDENTIAL_UNAVAILABLE, connector, f"The named connection cannot be used: {incomplete}",
                **{"connection": target.name, "connection_id": target.id},
            )) from None
    return ServiceConnection(connection_ref(target), connection_name(target), config)


def planned_tool_config(tool_name: str, params: dict[str, Any] | None, base: dict[str, Any] | None, *,
                        agent_tool: bool = True) -> dict[str, Any]:
    """The non-secret config the tool router would run ``tool_name`` with these ``params`` on (``{}`` if refused).
    ``agent_tool=False``: the platform's own use (a workflow step), which a connection's agent tools level does not
    limit."""
    merged = base if isinstance(base, dict) else {}
    plan = plan_route(tool_name, params, merged, agent_tool=agent_tool)
    if plan.refusal is not None or plan.fan_out or len(plan.targets) > 1:
        return {}
    if plan.passthrough or plan.descriptor is None:
        return _plain(merged)
    return connection_config(merged, plan.descriptor.connector, routes_of(merged), plan.targets[0])


def usable_connection_ids(connector: str, base: dict[str, Any] | None) -> list[str]:
    """The connections that could serve a use without a key, in the router's order: the Workspace's named
    connections, then the global ones, then the default entry when it has a target (``default``)."""
    descriptor = descriptor_of(connector)
    merged = base if isinstance(base, dict) else {}
    if descriptor is None:
        return []
    routes = routes_of(merged)
    if routes.unavailable:
        return []
    listed = [c.id for c in routes.of(connector) if usable(descriptor, c.config)]
    if usable(descriptor, connection_config(merged, connector, routes, None)):
        listed.append(connection_ref(None))
    return listed


__all__ = [
    "ConnectionRefusalError",
    "ServiceConnection",
    "planned_tool_config",
    "service_connection_config",
    "usable_connection_ids",
]
