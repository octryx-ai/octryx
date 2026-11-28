"""The plan of one connector call (:class:`RoutePlan`) and the helpers its planner (``route_planner``), the connection
gate and the executors share: scope keys, refusals, usability and the candidates a refusal lists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import DEFAULT_CONNECTION_NAME, scope_key
from .descriptor import ConnectorDescriptor
from .resolver import connection_ref
from .routes_model import NamedConnectionRoutes, ResolvedNamedConnection

CONNECTION_PARAM = "connection"
REASON_CONNECTION_AMBIGUOUS = "connection_ambiguous"
REASON_CONNECTION_UNKNOWN = "connection_unknown"
REASON_CONNECTION_SCOPE_MISMATCH = "connection_scope_mismatch"


@dataclass(frozen=True, slots=True)
class RoutePlan:
    descriptor: ConnectorDescriptor | None
    targets: tuple[ResolvedNamedConnection | None, ...] = ()
    keys: tuple[str, ...] = ()
    fan_out: bool = False
    passthrough: bool = False
    refusal: dict[str, Any] | None = None
    skipped: tuple[dict[str, Any], ...] = ()  # fan-out connections the grants exclude (``connection_gate``)

    @property
    def connection_ids(self) -> tuple[str, ...]:
        if self.refusal is not None or self.descriptor is None:
            return ()
        if self.passthrough:
            return (DEFAULT_CONNECTION_NAME,)
        return tuple(connection_ref(target) for target in self.targets)


def clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def scope_keys(descriptor: ConnectorDescriptor, tool_name: str, params: dict) -> tuple[str, ...]:
    keys: list[str] = []
    for key in descriptor.request_keys(tool_name, params):
        if clean_text(key) and scope_key(descriptor.connector, key) not in keys:
            keys.append(scope_key(descriptor.connector, key))
    return tuple(keys)


def refusal(code: str, tool: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, "code": code, "connector": tool, **extra}


def usable(descriptor: ConnectorDescriptor, config: dict) -> bool:
    return descriptor.usable(config)


def candidates(routes: NamedConnectionRoutes, tool: str) -> list[dict[str, Any]]:
    listed = [
        {"id": c.id, "name": c.name, "scope": c.scope, "binds": sorted(c.bound_scopes)} for c in routes.of(tool)
    ]
    return [*listed, {"id": DEFAULT_CONNECTION_NAME, "name": DEFAULT_CONNECTION_NAME, "scope": "connector"}]


__all__ = [
    "CONNECTION_PARAM",
    "REASON_CONNECTION_AMBIGUOUS",
    "REASON_CONNECTION_SCOPE_MISMATCH",
    "REASON_CONNECTION_UNKNOWN",
    "RoutePlan",
    "candidates",
    "clean_text",
    "refusal",
    "scope_keys",
    "usable",
]
