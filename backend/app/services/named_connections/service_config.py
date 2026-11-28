"""The connection a platform service uses outside a tool call: the tool router's plan, not the raw config."""

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
    def __init__(self, details: dict[str, Any]) -> None:
        super().__init__(str(details.get("error") or details.get("code") or "connection refused"))
        self.code = str(details.get("code") or "")
        self.details = details


@dataclass(frozen=True, slots=True)
class ServiceConnection:
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
    merged = base if isinstance(base, dict) else {}
    plan = plan_route(tool_name, params, merged, agent_tool=agent_tool)
    if plan.refusal is not None or plan.fan_out or len(plan.targets) > 1:
        return {}
    if plan.passthrough or plan.descriptor is None:
        return _plain(merged)
    return connection_config(merged, plan.descriptor.connector, routes_of(merged), plan.targets[0])


def usable_connection_ids(connector: str, base: dict[str, Any] | None) -> list[str]:
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
