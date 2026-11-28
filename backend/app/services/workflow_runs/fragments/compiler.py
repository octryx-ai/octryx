"""The fragment compiler: a composite source and its pinned fragments become one ordinary phased graph."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .format import (
    FRAGMENT_EDGES_KEY,
    INSTANCE_SINGLE,
    MAX_NODE_ID,
    NODE_FRAGMENT,
    FragmentDefinition,
    FragmentError,
    FragmentRef,
    ResolvedFragment,
    edge_source,
    edge_target,
    error,
    fragment_refs,
    is_marker,
    parse_fragment,
)
from .node_refs import rewrite_node_refs

COMPOSITION_SCHEMA = "composition/v1"
_PORT_KINDS = {"pause": "pause", "outcome": "outcome"}


@dataclass(frozen=True, slots=True)
class Composition:
    definition: dict
    provenance: dict[str, dict]
    edge_provenance: dict[str, dict]
    fragments: list[dict]
    source_hash: str
    compiled_digest: str


def canonical_hash(value: Any) -> str:
    from ..handoff.contract import canonical_hash as _hash

    return _hash(value)


def _digest(definition: dict[str, Any]) -> str:
    from ..seeding import definition_digest

    return definition_digest(definition)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _pin(ref: FragmentRef, resolved: ResolvedFragment) -> dict[str, Any]:
    return {"ref": ref.node_id, "key": resolved.key, "version": resolved.version,
            "version_id": resolved.version_id, "checksum": resolved.checksum}


def _check_pins(refs: list[FragmentRef], resolved: Mapping[str, ResolvedFragment]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for ref in refs:
        item = resolved.get(ref.node_id)
        if item is None:
            errors.append(error("fragment_pin_unresolved", f"Fragment reference '{ref.node_id}': no published "
                                                           f"version of '{ref.fragment_key}' with its checksum."))
            continue
        if item.key != ref.fragment_key:
            errors.append(error("fragment_pin_unresolved", f"Fragment reference '{ref.node_id}' pins "
                                                           f"'{ref.fragment_key}', not '{item.key}'."))
        if item.checksum != ref.checksum or (ref.version_id is not None and item.version_id != ref.version_id):
            errors.append(error("fragment_pin_changed", f"Fragment reference '{ref.node_id}': the pinned version "
                                                        "and checksum are not the same content; re-pin it."))
    return errors


def _check_refs(source: dict[str, Any], refs: list[FragmentRef],
                resolved: Mapping[str, ResolvedFragment]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    ids = [ref.node_id for ref in refs]
    for ref_id in sorted({item for item in ids if ids.count(item) > 1}):
        errors.append(error("fragment_id_collision", f"Two fragment references share the id '{ref_id}'."))
    singles: dict[str, list[str]] = {}
    for ref in refs:
        item = resolved.get(ref.node_id)
        if item is None:
            continue
        definition = item.definition
        if any(_text(node.get("type")) == NODE_FRAGMENT for node in definition.nodes) or any(
                is_marker(edge) for edge in definition.edges):
            errors.append(error("fragment_nested", f"Fragment '{item.key}' references a fragment (no nesting)."))
        if definition.instance == INSTANCE_SINGLE:
            singles.setdefault(item.key, []).append(ref.node_id)
        for port in sorted(set(definition.ports) - set(ref.ports)):
            errors.append(error("fragment_port_unmapped", f"Fragment reference '{ref.node_id}' maps no node to "
                                                          f"port '{port}'."))
        for port in sorted(set(ref.ports) - set(definition.ports)):
            errors.append(error("fragment_port_unknown", f"Fragment reference '{ref.node_id}' maps port '{port}', "
                                                         f"which '{item.key}' does not declare."))
    for key, used in singles.items():
        if len(used) > 1:
            errors.append(error("fragment_single_instance", f"Fragment '{key}' runs once per run (instance: single)"
                                                            f"; it is referenced by {', '.join(used)}."))
    ref_ids = set(ids)
    for edge in source.get("edges") or []:
        if isinstance(edge, dict) and not is_marker(edge) and edge_source(edge)[1] in ref_ids:
            errors.append(error("fragment_ref_exit", f"Edge '{_text(edge.get('id'))}' leaves fragment reference "
                                                     f"'{edge_source(edge)[1]}': its exits are its ports."))
    markers = [_text(edge.get(FRAGMENT_EDGES_KEY)) for edge in source.get("edges") or [] if is_marker(edge)]
    for name in markers:
        if name not in ref_ids:
            errors.append(error("fragment_marker_unknown", f"The edge marker names no fragment reference '{name}'."))
    for name in sorted({item for item in markers if markers.count(item) > 1}):
        errors.append(error("fragment_marker_duplicate", f"Two edge markers splice fragment reference '{name}'."))
    return errors


def _instance_nodes(ref: FragmentRef, item: ResolvedFragment) -> list[dict[str, Any]]:
    local = {_text(node.get("id")) for node in item.definition.nodes}

    def rename(node_id: str) -> str:
        return ref.namespace + node_id if node_id in local else node_id

    compiled = []
    for node in item.definition.nodes:
        copied = rewrite_node_refs(node, rename)
        compiled.append({key: (ref.namespace + value if key == "id" else value) for key, value in copied.items()})
    return compiled


def _instance_edges(ref: FragmentRef, item: ResolvedFragment,
                    entries: Mapping[str, str]) -> list[tuple[dict[str, Any], str]]:
    compiled = []
    for edge in item.definition.edges:
        out: dict[str, Any] = {}
        for key, value in edge.items():
            if key in ("id", "source_node_id", "target_node_id"):
                out[key] = ref.namespace + _text(value)
            elif key == "target_port":
                target = ref.ports.get(_text(value), "")
                out["target_node_id"] = entries.get(target, target)
            else:
                out[key] = copy.deepcopy(value)
        compiled.append((out, _text(edge.get("id"))))
    return compiled


def _build(source: dict[str, Any], refs: list[FragmentRef], resolved: Mapping[str, ResolvedFragment]):
    by_id = {ref.node_id: ref for ref in refs}
    provenance: dict[str, dict] = {}
    edge_provenance: dict[str, dict] = {}
    instances: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for raw in source.get("nodes") or []:
        ref = by_id.get(_text(raw.get("id"))) if isinstance(raw, dict) and _text(raw.get("type")) == NODE_FRAGMENT \
            else None
        if ref is None:
            nodes.append(copy.deepcopy(raw))
            continue
        item = resolved[ref.node_id]
        instance = {**_pin(ref, item), "namespace": ref.namespace, "nodes": [], "edges": []}
        for node, original in zip(_instance_nodes(ref, item), item.definition.nodes, strict=True):
            nodes.append(node)
            instance["nodes"].append(node["id"])
            provenance[node["id"]] = {**_pin(ref, item), "node": _text(original.get("id"))}
        instances[ref.node_id] = instance

    def splice(ref_id: str) -> list[dict[str, Any]]:
        ref, item = by_id[ref_id], resolved[ref_id]
        spliced = []
        for edge, original in _instance_edges(ref, item, entries):
            spliced.append(edge)
            instances[ref_id]["edges"].append(edge["id"])
            edge_provenance[edge["id"]] = {**_pin(ref, item), "edge": original}
        return spliced

    entries = {ref.node_id: ref.namespace + resolved[ref.node_id].definition.entry for ref in refs}
    edges: list[dict[str, Any]] = []
    spliced: set[str] = set()
    for raw in source.get("edges") or []:
        if is_marker(raw):
            name = _text(raw.get(FRAGMENT_EDGES_KEY))
            edges.extend(splice(name))
            spliced.add(name)
            continue
        edge = copy.deepcopy(raw)
        key, target = edge_target(edge) if isinstance(edge, dict) else ("", "")
        if target in entries:
            edge[key] = entries[target]
        edges.append(edge)
    for ref in refs:
        if ref.node_id not in spliced:
            edges.extend(splice(ref.node_id))
    definition = {}
    for key, value in source.items():
        definition[key] = nodes if key == "nodes" else edges if key == "edges" else copy.deepcopy(value)
    definition.setdefault("nodes", nodes)
    definition.setdefault("edges", edges)
    fragments = [instances[ref.node_id] for ref in refs]
    return definition, provenance, edge_provenance, fragments


def _check_compiled(definition: dict[str, Any], refs: list[FragmentRef],
                    resolved: Mapping[str, ResolvedFragment]) -> list[dict[str, str]]:
    from ..data_flow import produces
    from ..graph import parse_phased_definition
    from ..graph_validation import _ancestors

    errors: list[dict[str, str]] = []
    entries = {ref.node_id: ref.namespace + resolved[ref.node_id].definition.entry for ref in refs}
    for label, items in (("node", definition["nodes"]), ("edge", definition["edges"])):
        ids = [_text(item.get("id")) for item in items if isinstance(item, dict) and _text(item.get("id"))]
        for item_id in sorted({item for item in ids if ids.count(item) > 1}):
            errors.append(error("fragment_id_collision", f"The compiled graph has two {label}s '{item_id}'; give "
                                                         "the fragment reference a namespace."))
        if label == "node":
            for item_id in ids:
                if len(item_id) > MAX_NODE_ID:
                    errors.append(error("fragment_node_id_too_long", f"Compiled node id '{item_id[:40]}…' is longer "
                                                                     f"than {MAX_NODE_ID} characters."))
    kinds = {_text(node.get("id")): _text(node.get("type")) for node in definition["nodes"] if isinstance(node, dict)}
    graph = parse_phased_definition(definition)
    for ref in refs:
        item = resolved[ref.node_id]
        for port_name, port in sorted(item.definition.ports.items()):
            target = ref.ports.get(port_name)
            if target is None:
                continue
            target = entries.get(target, target)
            if target not in kinds:
                errors.append(error("fragment_port_target_unknown", f"Fragment reference '{ref.node_id}' maps port "
                                                                    f"'{port_name}' to an unknown node '{target}'."))
            elif port.accepts in _PORT_KINDS and kinds[target] != _PORT_KINDS[port.accepts]:
                errors.append(error("fragment_port_target_kind", f"Port '{port_name}' of '{ref.node_id}' accepts a "
                                                                 f"{port.accepts}; '{target}' is a {kinds[target]}."))
        entry = ref.namespace + item.definition.entry
        available: set[str] = set()
        for ancestor in _ancestors(graph, entry):
            if ancestor in graph.nodes:
                available |= produces(graph.nodes[ancestor])
        missing = sorted(item.definition.requires - available)
        if missing:
            errors.append(error("fragment_input_missing", f"Fragment reference '{ref.node_id}' needs "
                                                          f"{', '.join(missing)} before its entry, but no step before "
                                                          "it produces it."))
    return errors


def compile_parts(source: dict, resolved: Mapping[str, ResolvedFragment]
                  ) -> tuple[Composition | None, list[dict[str, str]]]:
    try:
        refs = fragment_refs(source)
    except FragmentError as exc:
        return None, exc.errors
    errors = _check_pins(refs, resolved)
    errors += _check_refs(source, refs, resolved)
    if errors:
        return None, errors
    definition, provenance, edge_provenance, fragments = _build(source, refs, resolved)
    errors = _check_compiled(definition, refs, resolved)
    return Composition(definition=definition, provenance=provenance, edge_provenance=edge_provenance,
                       fragments=fragments, source_hash=canonical_hash(source),
                       compiled_digest=_digest(definition)), errors


def compile_composite(source: dict, resolved: Mapping[str, ResolvedFragment]) -> Composition:
    composition, errors = compile_parts(source, resolved)
    if errors or composition is None:
        raise FragmentError(errors)
    return composition


def composition_settings(composition: Composition, source: dict) -> dict:
    return {
        "schema": COMPOSITION_SCHEMA,
        "source": copy.deepcopy(source),
        "source_hash": composition.source_hash,
        "compiled_digest": composition.compiled_digest,
        "fragments": copy.deepcopy(composition.fragments),
        "provenance": copy.deepcopy(composition.provenance),
        "edge_provenance": copy.deepcopy(composition.edge_provenance),
    }


def resolve_seed_fragments(source: dict, fragment_seeds: list[dict[str, Any]]) -> dict[str, ResolvedFragment]:
    errors: list[dict[str, str]] = []
    resolved: dict[str, ResolvedFragment] = {}
    for ref in fragment_refs(source):
        candidates = [seed for seed in fragment_seeds if seed.get("key") == ref.fragment_key]
        match = next((seed for seed in candidates if canonical_hash(seed.get("definition")) == ref.checksum), None)
        if match is None:
            code = "fragment_pin_changed" if candidates else "fragment_pin_unresolved"
            errors.append(error(code, f"Fragment reference '{ref.node_id}': no shipped '{ref.fragment_key}' with its "
                                      "checksum."))
            continue
        try:
            definition: FragmentDefinition = parse_fragment(match["definition"])
        except FragmentError as exc:
            errors.extend(exc.errors)
            continue
        resolved[ref.node_id] = ResolvedFragment(key=ref.fragment_key, version_id=ref.version_id or "",
                                                 version=int(match.get("version") or 1), checksum=ref.checksum,
                                                 definition=definition)
    if errors:
        raise FragmentError(errors)
    return resolved


__all__ = ["COMPOSITION_SCHEMA", "Composition", "compile_composite", "compile_parts", "composition_settings",
           "resolve_seed_fragments"]
