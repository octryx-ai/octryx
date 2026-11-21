"""The tool parameters named connections add to every routed tool's definition.

Every tool of a descriptor connector gets the optional ``connection`` (a named connection's id or name, or
``default``) plus the parameters its descriptor declares so a call can name its binding key
(``ConnectorDescriptor.request_params``, e.g. a Kubernetes ``cluster``). The router strips ``connection``
before the tool runs; the descriptor's own parameters reach the tool.
"""

from __future__ import annotations

import copy
from typing import Any

from .descriptors import descriptor_for_tool, shared_claimants
from .route_plan import CONNECTION_PARAM


def _connection_schema(label: str, key_label: str) -> dict[str, Any]:
    return {
        "type": "string",
        # Sent with every routed tool on every model call (several times per chat
        # request); an ambiguous call is still refused with the candidates, which says the rest.
        "description": f"Optional {label} connection (id, name or 'default'); omitted: routed by its {key_label}.",
    }


def with_connection_params(definitions: dict[str, dict]) -> dict[str, dict]:
    """``definitions`` with the routing parameters added to each routed tool (others unchanged, same objects)."""
    result: dict[str, dict] = {}
    for name, definition in definitions.items():
        descriptor = descriptor_for_tool(name)
        claimants = (descriptor,) if descriptor is not None else shared_claimants(name)
        parameters = (definition.get("function") or {}).get("parameters") if isinstance(definition, dict) else None
        if not claimants or not isinstance(parameters, dict):
            result[name] = definition
            continue
        extended = copy.deepcopy(definition)
        properties = extended["function"]["parameters"].setdefault("properties", {})
        for claimant in claimants:
            for param, schema in claimant.request_params.items():
                properties.setdefault(param, dict(schema))
        label = " or ".join(claimant.label for claimant in claimants)
        key_label = " or ".join(dict.fromkeys(claimant.binding.label for claimant in claimants))
        properties.setdefault(CONNECTION_PARAM, _connection_schema(label, key_label))
        result[name] = extended
    return result


__all__ = ["with_connection_params"]
