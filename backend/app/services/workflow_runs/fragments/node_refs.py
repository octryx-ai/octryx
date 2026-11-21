"""The closed table of node-id-valued config keys: what the compiler renames when it namespaces a fragment.

A key whose value names another node of the same graph must be renamed with the node it names, otherwise a
namespaced fragment would point at a node that no longer exists (or, worse, at a composite node of the same id).
``tests/test_s4_node_ref_keys.py`` guards the table: a new ``config.get(...)`` read in the workflow runtime is either
listed here or declared as not naming a node.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

NODE_REF_KEYS: frozenset[tuple[str, str]] = frozenset({
    ("gate", "phase"),                      # graph._validate_node, engine._gate_evidence, test_runs
    ("decision", "source"),                 # conditions (validation, decision_route)
    ("review", "producer"),                 # review.artefact_contract / artefact_evidence (artefact mode)
    ("review", "phase"),                    # review.screens.reviewed_phase, runner (the phase the review checks)
    ("review", "screens_node"),             # review.screens / runner (whose screenshots the review shows)
    ("user_confirmation", "payload_from"),  # data_flow, confirmation_payloads
})
DEFINITION_NODE_REF_KEYS = frozenset({"plan_node"})


def _refs(node: dict[str, Any]) -> list[tuple[str, str]]:
    kind = str(node.get("type") or "").strip()
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    return [(key, config[key]) for node_kind, key in sorted(NODE_REF_KEYS)
            if node_kind == kind and isinstance(config.get(key), str) and config[key].strip()]


def rewrite_node_refs(node: dict[str, Any], rename: Callable[[str], str]) -> dict[str, Any]:
    """A deep copy of ``node`` whose node-id-valued config values are renamed (its own id is left to the caller)."""
    copied = copy.deepcopy(node)
    for key, value in _refs(node):
        copied["config"][key] = rename(value)
    return copied


def external_refs(node: dict[str, Any], local_ids: set[str]) -> list[str]:
    """The node ids ``node`` names that are not in ``local_ids`` (a fragment may only name its own nodes)."""
    return [value for _key, value in _refs(node) if value not in local_ids]


__all__ = ["DEFINITION_NODE_REF_KEYS", "NODE_REF_KEYS", "external_refs", "rewrite_node_refs"]
