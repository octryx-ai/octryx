"""A phase's steps and checks as a Canvas graph. Pure.

The graph is a view of the stored definition, never a second storage. Two kinds of nodes:

- **stored**: ``step`` nodes carry the raw ``workflow_contract.source_steps`` entry unchanged (``step``), ``check``
  nodes the raw ``workflow_contract.checks`` entry (``check``). Their order in ``nodes`` is the definition order.
- **derived** (``derived: true``): ``start``, ``approval`` (the capability class asks the user first, or a step's
  tool declares ``approval_required``) and ``result``. They explain the run and are ignored on the way back.

``definition_from_graph(payload, definition_graph(payload)) == payload`` for every version payload: only
``source_steps`` and ``checks`` are rebuilt, from the raw entries the graph carries.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..run_capability.definition_contract import declared_workflow_capability
from ..workflow_checks.library import ADVISORY_ONLY_TYPES
from ..workflow_checks.steps import STEP_MODES, default_step_mode
from ..workflow_routing.tool_policy import tool_name_is_allowed_by_policy

GRAPH_SCHEMA = "workflow_steps_graph/1"
STEPS_KEY = "source_steps"
CHECKS_KEY = "checks"
CONFIRM_FIRST_CLASSES = frozenset({"change", "deliver"})
NODE_START, NODE_APPROVAL, NODE_STEP, NODE_CHECK, NODE_RESULT = "start", "approval", "step", "check", "result"
DERIVED_KINDS = frozenset({NODE_START, NODE_APPROVAL, NODE_RESULT})


class GraphShapeError(ValueError):
    """The posted graph cannot become a definition; ``code`` names the closed reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = payload.get("workflow_contract")
    return contract if isinstance(contract, dict) else {}


def _entries(contract: Mapping[str, Any], key: str) -> list[Any]:
    value = contract.get(key)
    return list(value) if isinstance(value, list) else []


def _step_node(index: int, raw: Any, *, default_mode: str, tool_policy: Mapping[str, Any]) -> dict[str, Any]:
    step = raw if isinstance(raw, Mapping) else {}
    tool = str(step.get("tool") or "").strip()
    mode = str(step.get("mode") or "")
    return {
        "id": f"step-{index}",
        "kind": NODE_STEP,
        "step": deepcopy(raw),
        "tool": tool,
        "label": str(step.get("evidence_label") or step.get("label") or ""),
        "required": step.get("required") is not False,
        "mode": mode if mode in STEP_MODES else default_mode,
        "mode_explicit": mode in STEP_MODES,
        "allowed": bool(tool) and tool_name_is_allowed_by_policy(tool, dict(tool_policy)),
    }


def _check_node(index: int, raw: Any) -> dict[str, Any]:
    check = raw if isinstance(raw, Mapping) else {}
    kind = str(check.get("type") or "")
    return {
        "id": f"check-{index}",
        "kind": NODE_CHECK,
        "check": deepcopy(raw),
        "type": kind,
        "description": str(check.get("description") or ""),
        "blocking": check.get("blocking") is True and kind not in ADVISORY_ONLY_TYPES,
    }


def definition_graph(
    payload: Mapping[str, Any], *, tool_requires_approval: Callable[[str], bool] = lambda _name: False
) -> dict[str, Any]:
    """``{schema, capability_class, nodes, edges}`` of one version payload (see the module docstring)."""
    contract = _contract(payload)
    tool_policy = payload.get("tool_policy") if isinstance(payload.get("tool_policy"), Mapping) else {}
    capability = declared_workflow_capability(
        {"workflow_contract": contract, "safety_constraints": payload.get("safety_constraints")}
    ).capability_class
    default_mode = default_step_mode(str(contract.get("capability_class") or ""))
    nodes: list[dict[str, Any]] = [{"id": "start", "kind": NODE_START, "derived": True}]
    if capability in CONFIRM_FIRST_CLASSES:
        nodes.append({"id": "approval-class", "kind": NODE_APPROVAL, "derived": True, "reason": "capability_class",
                      "capability_class": capability})
    for index, raw in enumerate(_entries(contract, STEPS_KEY)):
        node = _step_node(index, raw, default_mode=default_mode, tool_policy=tool_policy)
        if node["tool"] and tool_requires_approval(node["tool"]):
            nodes.append({"id": f"approval-{node['id']}", "kind": NODE_APPROVAL, "derived": True,
                          "reason": "tool_approval_required", "tool": node["tool"]})
        nodes.append(node)
    nodes.extend(_check_node(index, raw) for index, raw in enumerate(_entries(contract, CHECKS_KEY)))
    nodes.append({"id": "result", "kind": NODE_RESULT, "derived": True})
    edges = [
        {"id": f"{source['id']}->{target['id']}", "source": source["id"], "target": target["id"]}
        for source, target in zip(nodes, nodes[1:], strict=False)
    ]
    return {"schema": GRAPH_SCHEMA, "capability_class": capability, "nodes": nodes, "edges": edges}


def _stored_entries(graph: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
    if not isinstance(nodes, list):
        raise GraphShapeError("invalid_graph", "graph.nodes must be a list")
    steps: list[Any] = []
    checks: list[Any] = []
    for index, node in enumerate(nodes):
        kind = str(node.get("kind") or "") if isinstance(node, Mapping) else ""
        if kind in DERIVED_KINDS:
            continue
        if kind == NODE_STEP and isinstance(node.get("step"), Mapping):
            steps.append(deepcopy(dict(node["step"])))
        elif kind == NODE_CHECK and isinstance(node.get("check"), Mapping):
            checks.append(deepcopy(dict(node["check"])))
        else:
            raise GraphShapeError(
                "invalid_graph_node", f"graph.nodes[{index}] must be a step with `step` or a check with `check`"
            )
    return steps, checks


def definition_from_graph(payload: Mapping[str, Any], graph: Mapping[str, Any]) -> dict[str, Any]:
    """``payload`` with ``source_steps`` and ``checks`` taken from the graph's stored nodes, in their order.

    A key the stored definition did not have stays absent while the graph has no node of that kind, so an
    unedited graph returns the payload unchanged.
    """
    steps, checks = _stored_entries(graph)
    result = deepcopy(dict(payload))
    contract = dict(_contract(result))
    for key, entries in ((STEPS_KEY, steps), (CHECKS_KEY, checks)):
        if entries or key in contract:
            contract[key] = entries
    result["workflow_contract"] = contract
    return result


__all__ = [
    "GRAPH_SCHEMA",
    "GraphShapeError",
    "definition_from_graph",
    "definition_graph",
]
