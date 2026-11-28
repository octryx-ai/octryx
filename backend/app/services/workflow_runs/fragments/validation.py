"""Validation of a fragment and of a composed graph, through the unchanged phased validator."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .compiler import canonical_hash, compile_parts
from .format import (
    FRAGMENT_KIND,
    FragmentDefinition,
    FragmentError,
    ResolvedFragment,
    error,
    parse_fragment,
)
from .node_refs import external_refs

SYNTHETIC_PREFIX = "__"
_CONSUMER_NODE = re.compile(r"^Node '([^']+)' needs ")


def _text(value: Any) -> str:
    return str(value or "").strip()


def known_kinds() -> frozenset[str]:
    from ..data_flow import (
        CHANGE_PLAN,
        CONFIRMED_TESTS,
        HANDOFF_INPUT_KINDS,
        REVIEW_VERDICT,
        SUBJECT_REQUIRES,
        TEXT_SOURCE_REQUIRES,
    )
    from ..documentation.flow import CONFIRMED_DOCUMENTATION, DOCUMENTATION_PAGE
    from ..phase_outputs import OUTPUT_SPECS

    return frozenset(OUTPUT_SPECS) | {CHANGE_PLAN, CONFIRMED_TESTS, REVIEW_VERDICT, "artefact_review_verdict",
                                      CONFIRMED_DOCUMENTATION, DOCUMENTATION_PAGE} | HANDOFF_INPUT_KINDS | set(
        SUBJECT_REQUIRES.values()) | set(TEXT_SOURCE_REQUIRES.values())


def harness_definition(fragment: FragmentDefinition) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [{"id": "__start", "type": "start"}, *fragment.nodes]
    edges: list[dict[str, Any]] = [{"id": "__e_start", "source_node_id": "__start",
                                    "target_node_id": fragment.entry}]
    targets: dict[str, str] = {}
    for name, port in sorted(fragment.ports.items()):
        if port.edge == "loop":
            targets[name] = "__start"
        elif port.accepts == "pause":
            targets[name] = f"__pause_{name}"
            nodes.append({"id": targets[name], "type": "pause", "config": {"reason": "action_failed"}})
            edges.append({"id": f"__e_pause_{name}", "source_node_id": targets[name], "target_node_id": "__end"})
        else:
            targets[name] = f"__end_{name}"
            nodes.append({"id": targets[name], "type": "outcome", "config": {"outcome": "done"}})
    if any(port.accepts == "pause" and port.edge != "loop" for port in fragment.ports.values()):
        nodes.append({"id": "__end", "type": "outcome", "config": {"outcome": "blocked"}})
    for edge in fragment.edges:
        wrapped = {key: value for key, value in edge.items() if key != "target_port"}
        if "target_port" in edge:
            wrapped["target_node_id"] = targets.get(_text(edge["target_port"]), "")
        edges.append(wrapped)
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}


def _harness_errors(fragment: FragmentDefinition) -> list[dict[str, str]]:
    from ..data_flow import missing_producers
    from ..graph import parse_phased_definition
    from ..graph_validation import validate_phased_definition

    harness = harness_definition(fragment)
    graph = parse_phased_definition(harness)
    kept: list[dict[str, str]] = []
    for item in validate_phased_definition(harness)["errors"]:
        # A problem of the synthetic harness itself (its start, ends, pauses or their arrows), not of the fragment.
        if f"'{SYNTHETIC_PREFIX}" in item["message"] or _text(item.get("edge_id")).startswith(SYNTHETIC_PREFIX) or (
                not item.get("edge_id") and _text(item.get("node_id")).startswith(SYNTHETIC_PREFIX)):
            continue
        if item["code"] == "consumer_without_producer":
            match = _CONSUMER_NODE.match(item["message"])
            node = graph.nodes.get(match.group(1)) if match else None
            if node is not None and not set(missing_producers(graph, node)) - fragment.requires:
                continue
        kept.append(item)
    return kept


def _rule_errors(fragment: FragmentDefinition) -> list[dict[str, str]]:
    from ..data_flow import produces
    from ..graph import parse_phased_definition

    errors: list[dict[str, str]] = []
    used = {_text(edge.get("target_port")) for edge in fragment.edges if _text(edge.get("target_port"))}
    for name in sorted(set(fragment.ports) - used):
        errors.append(error("fragment_port_unused", f"Port '{name}' is declared, but no edge exits through it."))
    local = {_text(node.get("id")) for node in fragment.nodes}
    for node in fragment.nodes:
        for target in external_refs(node, local):
            errors.append(error("fragment_external_ref", f"Node '{node['id']}' names '{target}', which is not a node "
                                                         "of the fragment."))
    graph = parse_phased_definition({"nodes": list(fragment.nodes), "edges": []})
    produced: set[str] = set()
    for node in graph.nodes.values():
        produced |= produces(node)
    for kind in sorted(fragment.provides - produced):
        errors.append(error("fragment_provides", f"The fragment provides '{kind}', but none of its nodes produces "
                                                 "it."))
    for kind in sorted(fragment.requires - known_kinds()):
        errors.append(error("fragment_requires", f"The fragment requires an unknown artefact kind '{kind}'."))
    return errors


def _report(errors: list[dict[str, str]], definition: dict[str, Any]) -> dict[str, Any]:
    nodes = [node for node in definition.get("nodes") or [] if isinstance(node, dict)] if isinstance(
        definition, dict) else []
    edges = definition.get("edges") if isinstance(definition, dict) and isinstance(definition.get("edges"), list) \
        else []
    return {"valid": not errors, "errors": errors, "warnings": [], "node_count": len(nodes),
            "edge_count": len(edges), "node_types": sorted({_text(node.get("type")) for node in nodes} - {""}),
            "execution_kind": FRAGMENT_KIND}


def validate_fragment_definition(definition: dict) -> dict:
    try:
        fragment = parse_fragment(definition)
    except FragmentError as exc:
        return _report(exc.errors, definition)
    report = _report(_rule_errors(fragment) + _harness_errors(fragment), definition)
    report["ports"] = sorted(fragment.ports)
    return report


def _analysis(instance: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    from ..platform.catalog import DEPLOY_RUN, action_class

    ids = set(instance["nodes"])
    nodes = [node for node in definition["nodes"] if node.get("id") in ids]
    actions = [dict(node.get("config") or {}) for node in nodes if node.get("type") == "platform_action"]
    phases = [dict(dict(node.get("config") or {}).get("workflow_contract") or {}) for node in nodes
              if node.get("type") == "phase"]
    return {**instance,
            "action_classes": sorted({action_class(config) for config in actions}),
            "phase_classes": sorted({_text(contract.get("capability_class")) for contract in phases} - {""}),
            "deploy": any(_text(config.get("action")) == DEPLOY_RUN for config in actions),
            "approval": any(node.get("type") == "approval" for node in nodes)}


def validate_composition(source: dict, resolved: Mapping[str, ResolvedFragment]) -> dict:
    from ..graph import EXECUTION_KIND_PHASED
    from ..graph_validation import validate_phased_definition

    composition, errors = compile_parts(source, resolved)
    if composition is None:
        return {"valid": False, "errors": errors, "warnings": [], "node_count": 0, "edge_count": 0,
                "node_types": [], "execution_kind": EXECUTION_KIND_PHASED,
                "composition": {"fragments": [], "compiled_digest": None, "source_hash": canonical_hash(source)}}
    report = validate_phased_definition(composition.definition)
    report["errors"] = errors + report["errors"]
    report["valid"] = not report["errors"]
    report["composition"] = {
        "fragments": [_analysis(item, composition.definition) for item in composition.fragments],
        "compiled_digest": composition.compiled_digest,
        "source_hash": composition.source_hash,
    }
    return report


__all__ = ["harness_definition", "known_kinds", "validate_composition", "validate_fragment_definition"]
