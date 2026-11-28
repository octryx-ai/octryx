"""The closed table of node-id-valued config keys: what the compiler renames when it namespaces a fragment."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

NODE_REF_KEYS: frozenset[tuple[str, str]] = frozenset({
    ("gate", "phase"),
    ("decision", "source"),
    ("review", "producer"),
    ("review", "phase"),
    ("review", "screens_node"),
    ("user_confirmation", "payload_from"),
})
DEFINITION_NODE_REF_KEYS = frozenset({"plan_node"})


def _refs(node: dict[str, Any]) -> list[tuple[str, str]]:
    kind = str(node.get("type") or "").strip()
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    return [(key, config[key]) for node_kind, key in sorted(NODE_REF_KEYS)
            if node_kind == kind and isinstance(config.get(key), str) and config[key].strip()]


def rewrite_node_refs(node: dict[str, Any], rename: Callable[[str], str]) -> dict[str, Any]:
    copied = copy.deepcopy(node)
    for key, value in _refs(node):
        copied["config"][key] = rename(value)
    return copied


def external_refs(node: dict[str, Any], local_ids: set[str]) -> list[str]:
    return [value for _key, value in _refs(node) if value not in local_ids]


__all__ = ["DEFINITION_NODE_REF_KEYS", "NODE_REF_KEYS", "external_refs", "rewrite_node_refs"]
