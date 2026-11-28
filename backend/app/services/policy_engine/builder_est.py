"""Reading Cedar's EST (``cedarpy.policies_to_json_str``) for the builder's parse."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RefusedError(Exception):
    pass


def path(node: Any) -> tuple[str, ...]:
    if isinstance(node, Mapping) and "Var" in node:
        return (str(node["Var"]),)
    if isinstance(node, Mapping) and isinstance(node.get("."), Mapping):
        return (*path(node["."]["left"]), str(node["."]["attr"]))
    raise RefusedError


def strings(node: Any) -> tuple[str, ...]:
    items = node.get("Set") if isinstance(node, Mapping) else None
    if not isinstance(items, list) or not items:
        raise RefusedError
    values = [item.get("Value") if isinstance(item, Mapping) else None for item in items]
    if not all(isinstance(value, str) for value in values):
        raise RefusedError
    return tuple(values)


def entities(node: Any, kind: str) -> tuple[str, ...]:
    items = node.get("Set") if isinstance(node, Mapping) else None
    if not isinstance(items, list) or not items:
        raise RefusedError
    found = []
    for item in items:
        ref = item.get("Value", {}).get("__entity") if isinstance(item, Mapping) else None
        if not isinstance(ref, Mapping) or ref.get("type") != kind:
            raise RefusedError
        found.append(str(ref["id"]))
    return tuple(found)


def value(node: Any) -> Any:
    if not isinstance(node, Mapping) or "Value" not in node:
        raise RefusedError
    return node["Value"]


def chain(node: Any, operator: str) -> list[Any]:
    if isinstance(node, Mapping) and set(node) == {operator}:
        return [*chain(node[operator]["left"], operator), *chain(node[operator]["right"], operator)]
    return [node]


def op(node: Any) -> tuple[str, Any]:
    if not isinstance(node, Mapping) or len(node) != 1:
        raise RefusedError
    return next(iter(node.items()))


class Found:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def put(self, key: str, item: Any) -> None:
        self.values[key] = item


__all__ = ["Found", "RefusedError", "chain", "entities", "op", "path", "strings", "value"]
