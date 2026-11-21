"""Translate between an Agent Definition and a visual Agent Designer document.

The Agent Designer (the static, network-free PySpur fork) edits a graph
document ``{name, description, definition: {nodes, links, test_inputs, spur_type}}``.
An Octryx Agent Definition is a definition plus an *ordered* list of steps.
This module is the only place where one becomes the other, and it is pure: no I/O,
no session, no model access.

Contract (designer document -> definition):

- exactly one ``InputNode`` and one ``OutputNode``;
- every other node is a step node (``SingleLLMCallNode`` or ``AgentNode``); any
  other node type is refused with ``unsupported_node_type`` rather than dropped;
- the links form one simple path Input -> step... -> Output that visits every node
  exactly once (``graph_not_linear`` otherwise), and no node is nested in a group;
- a step node becomes a step: title -> ``name``, ``system_message`` -> ``instructions``.
  Its designer-only fields (coordinates, user message, generation settings) are kept
  under ``step_config["designer"]`` so the next load shows the same canvas.

The model a step runs on is *not* taken from the designer's model picker: runtime
selection stays with the governed Runtime Priority. Refusals carry a stable ``code``
and the offending node ids only; no prompt text is echoed.
"""

from __future__ import annotations

from typing import Any

from .document_model import (
    _MAX_DESIGNER_SETTINGS_BYTES,
    _MAX_DOCUMENT_BYTES,
    _MAX_NAME,
    _MAX_NODES,
    _MAX_TEXT,
    _ROUND_TRIP_CONFIG_KEYS,
    _X_GAP,
    _X_START,
    _Y,
    DESIGNER_CONFIG_KEY,
    DOCUMENT_KIND,
    DOCUMENT_VERSION,
    INPUT_NODE,
    INPUT_NODE_ID,
    LLM_NODE,
    OUTPUT_NODE,
    OUTPUT_NODE_ID,
    STEP_NODE_TYPES,
    DesignerDefinition,
    DesignerDocumentError,
    DesignerIssue,
    DesignerStep,
    _config,
    _coordinates,
    _designer_settings,
    _json_size,
    _text,
)


def _linear_order(nodes: dict[str, dict[str, Any]], links: list[Any]) -> list[str] | None:
    """Return node ids from Input to Output if the links form one simple path."""
    successor: dict[str, str] = {}
    predecessors: dict[str, int] = {}
    for link in links:
        if not isinstance(link, dict):
            return None
        source, target = str(link.get("source_id") or ""), str(link.get("target_id") or "")
        if source not in nodes or target not in nodes or source in successor or source == target:
            return None
        successor[source] = target
        predecessors[target] = predecessors.get(target, 0) + 1
    if any(count != 1 for count in predecessors.values()):
        return None
    start = next(node_id for node_id, node in nodes.items() if node.get("node_type") == INPUT_NODE)
    order, current = [start], start
    while current in successor:
        current = successor[current]
        if current in order:
            return None
        order.append(current)
    if len(order) != len(nodes) or nodes[order[-1]].get("node_type") != OUTPUT_NODE:
        return None
    return order


def _indexed_nodes(document: Any) -> tuple[dict[str, dict[str, Any]], list[Any]]:
    """The document's nodes by id and its links; a malformed shape refuses at once."""
    if not isinstance(document, dict) or not isinstance(document.get("definition"), dict):
        raise DesignerDocumentError([DesignerIssue("malformed_document")])
    if _json_size(document) > _MAX_DOCUMENT_BYTES:
        raise DesignerDocumentError([DesignerIssue("document_too_large")])
    graph = document["definition"]
    raw_nodes, links = graph.get("nodes"), graph.get("links")
    if not isinstance(raw_nodes, list) or not isinstance(links, list) or len(raw_nodes) > _MAX_NODES:
        raise DesignerDocumentError([DesignerIssue("malformed_document")])
    nodes: dict[str, dict[str, Any]] = {}
    for node in raw_nodes:
        node_id = str(node.get("id") or "") if isinstance(node, dict) else ""
        if not node_id or node_id in nodes:
            raise DesignerDocumentError([DesignerIssue("malformed_document")])
        nodes[node_id] = node
    return nodes, links


def _node_issues(document: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[DesignerIssue]:
    issues: list[DesignerIssue] = []
    by_type: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        by_type.setdefault(str(node.get("node_type") or ""), []).append(node_id)
    unsupported = [
        node_id
        for node_type, ids in by_type.items()
        if node_type not in STEP_NODE_TYPES | {INPUT_NODE, OUTPUT_NODE}
        for node_id in ids
    ]
    if unsupported:
        issues.append(DesignerIssue("unsupported_node_type", tuple(sorted(unsupported))))
    if len(by_type.get(INPUT_NODE, [])) != 1 or len(by_type.get(OUTPUT_NODE, [])) != 1:
        issues.append(DesignerIssue("needs_one_input_and_one_output"))
    nested = [node_id for node_id, node in nodes.items() if node.get("parent_id")]
    if nested:
        issues.append(DesignerIssue("nested_nodes_not_supported", tuple(sorted(nested))))
    step_ids = [node_id for node_id in nodes if nodes[node_id].get("node_type") in STEP_NODE_TYPES]
    if not step_ids:
        issues.append(DesignerIssue("needs_at_least_one_step"))
    untitled = [node_id for node_id in step_ids if not _text(nodes[node_id].get("title"))]
    if untitled:
        issues.append(DesignerIssue("step_title_required", tuple(sorted(untitled))))
    # Over-long values are refused, never silently cut: a shortened prompt is a different agent.
    too_long = [
        node_id
        for node_id in step_ids
        if len(_text(nodes[node_id].get("title"))) > _MAX_NAME
        or len(_text(_config(nodes[node_id]).get("system_message"))) > _MAX_TEXT
        or _json_size(_designer_settings(_config(nodes[node_id]))) > _MAX_DESIGNER_SETTINGS_BYTES
    ]
    if len(_text(document.get("name"))) > _MAX_NAME or len(_text(document.get("description"))) > _MAX_TEXT:
        too_long.append("document")
    if too_long:
        issues.append(DesignerIssue("field_too_long", tuple(sorted(too_long))))
    return issues


def definition_from_document(document: Any) -> DesignerDefinition:
    """Validate a designer document and translate it; raise with every issue found."""
    nodes, links = _indexed_nodes(document)
    issues = _node_issues(document, nodes)
    if issues:
        raise DesignerDocumentError(issues)

    order = _linear_order(nodes, links)
    if order is None:
        raise DesignerDocumentError([DesignerIssue("graph_not_linear")])

    steps = []
    for index, node_id in enumerate(order[1:-1], start=1):
        node = nodes[node_id]
        config = _config(node)
        designer_config = _designer_settings(config)
        designer_config["node_type"] = node["node_type"]
        designer_config["coordinates"] = _coordinates(node, index)
        steps.append(
            DesignerStep(
                step_id=node_id,
                name=_text(node.get("title")),
                instructions=_text(config.get("system_message")),
                designer_config=designer_config,
            )
        )
    return DesignerDefinition(
        name=_text(document.get("name")),
        description=_text(document.get("description")),
        steps=steps,
    )


def document_from_definition(*, name: str, description: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the designer document for a definition's ordered, enabled-or-not steps.

    Each ``steps`` item carries ``id``, ``name``, ``instructions`` and ``step_config``.
    """
    nodes: list[dict[str, Any]] = [
        {
            "id": INPUT_NODE_ID,
            "title": "Input",
            "node_type": INPUT_NODE,
            "config": {"title": "Input"},
            "coordinates": {"x": _X_START, "y": _Y},
        }
    ]
    previous = INPUT_NODE_ID
    links: list[dict[str, str]] = []
    for index, step in enumerate(steps, start=1):
        step_config = step.get("step_config") if isinstance(step.get("step_config"), dict) else {}
        designer = (
            step_config.get(DESIGNER_CONFIG_KEY) if isinstance(step_config.get(DESIGNER_CONFIG_KEY), dict) else {}
        )
        node_type = designer.get("node_type") if designer.get("node_type") in STEP_NODE_TYPES else LLM_NODE
        config = {key: designer[key] for key in _ROUND_TRIP_CONFIG_KEYS if key in designer}
        config["system_message"] = str(step.get("instructions") or "")
        # The designer exports a node's title from ``config.title`` first, falling back to the
        # catalog default ("Single LLM Call"); without it every step would be renamed on save.
        config["title"] = str(step.get("name") or "")
        node_id = str(step["id"])
        nodes.append(
            {
                "id": node_id,
                "title": str(step.get("name") or ""),
                "node_type": node_type,
                "config": config,
                "coordinates": _coordinates({"coordinates": designer.get("coordinates")}, index),
            }
        )
        links.append({"source_id": previous, "target_id": node_id})
        previous = node_id
    nodes.append(
        {
            "id": OUTPUT_NODE_ID,
            "title": "Output",
            "node_type": OUTPUT_NODE,
            "config": {"title": "Output"},
            "coordinates": {"x": _X_START + (len(steps) + 1) * _X_GAP, "y": _Y},
        }
    )
    links.append({"source_id": previous, "target_id": OUTPUT_NODE_ID})
    return {
        "kind": DOCUMENT_KIND,
        "version": DOCUMENT_VERSION,
        "name": name,
        "description": description,
        "definition": {"nodes": nodes, "links": links, "test_inputs": [], "spur_type": "agent"},
    }


__all__ = [
    "definition_from_document",
    "document_from_definition",
]
