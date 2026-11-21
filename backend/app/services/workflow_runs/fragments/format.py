"""The fragment format (``fragment/v1``) and the reference node of a composite source.

A fragment definition (stored as an ordinary flow version)::

    {"execution_kind": "phased_fragment", "schema_version": "fragment/v1", "entry": "<node id>",
     "ports": {"<name>": {"edge": "next" | "loop", "accepts": "any" | "pause" | "outcome"}},
     "requires": [<artefact kind>], "provides": [<artefact kind>], "instance": "single" | "many",
     "nodes": [<phased node>], "edges": [<phased edge>; an exit edge has "target_port": <port> for its target]}

It has no start, outcome or pause (those belong to the composite, which the fragment reaches through its ports) and
no fragment reference (no nesting in v1). A composite source is a phased definition with at least one reference
node (``type: fragment``) or an edge-list splice marker (``{"fragment_edges": "<ref node id>"}``)::

    {"id": "<ref>", "type": "fragment", "config": {"fragment_key": ..., "fragment_version_id": ...,
     "fragment_checksum": "sha256:<64 hex>", "namespace": "" | "<name>.", "ports": {"<port>": "<node id>"}}}

The checksum (``handoff.contract.canonical_hash`` of the fragment's ``definition_json``) is the pin and is always
required; the version id is required on the API path (``fragments.store``) and optional for seeds. Parsing is pure;
every refusal is collected into one :class:`FragmentError` with ``{code, message}`` items like a validation report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..graph import EXECUTION_KIND_KEY, NODE_KINDS, NODE_OUTCOME, NODE_PAUSE, NODE_START, is_phased_definition

FRAGMENT_KIND = "phased_fragment"
FRAGMENT_SCHEMA = "fragment/v1"
NODE_FRAGMENT = "fragment"
FRAGMENT_EDGES_KEY = "fragment_edges"
PORT_EDGES = frozenset({"next", "loop"})
PORT_ACCEPTS = frozenset({"any", "pause", "outcome"})
INSTANCE_SINGLE, INSTANCE_MANY = "single", "many"
FRAGMENT_NODE_KINDS = NODE_KINDS - {NODE_START, NODE_OUTCOME, NODE_PAUSE}
NAMESPACE_RE = r"^(|[a-z][a-z0-9_]{0,31}\.)$"
MAX_NODE_ID = 128
PORT_NAME_RE = r"^[a-z][a-z0-9_]{0,31}$"
# What the composite owns; a fragment carries none of them.
DEFINITION_LEVEL_KEYS = frozenset({"plan_node", "failure_policy", "budget", "size_classes"})
_CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TARGET_KEYS = ("target_node_id", "target", "to_node_id", "to")
_SOURCE_KEYS = ("source_node_id", "source", "from_node_id", "from")


class FragmentError(ValueError):
    def __init__(self, errors: list[dict[str, str]]):
        self.errors = [dict(item) for item in errors]
        super().__init__("; ".join(f"{item['code']}: {item['message']}" for item in self.errors))


def error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


@dataclass(frozen=True, slots=True)
class FragmentPort:
    name: str
    edge: str
    accepts: str


@dataclass(frozen=True, slots=True)
class FragmentDefinition:
    entry: str
    ports: dict[str, FragmentPort]
    requires: frozenset[str]
    provides: frozenset[str]
    instance: str
    nodes: tuple[dict, ...]
    edges: tuple[dict, ...]
    raw: dict


@dataclass(frozen=True, slots=True)
class FragmentRef:
    node_id: str
    fragment_key: str
    version_id: str | None
    checksum: str
    namespace: str
    ports: dict[str, str]
    index: int


@dataclass(frozen=True, slots=True)
class ResolvedFragment:
    key: str
    version_id: str
    version: int
    checksum: str
    definition: FragmentDefinition


def _text(value: Any) -> str:
    return str(value or "").strip()


def edge_end(edge: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, str]:
    """The first non-empty end key of an edge and its value (``graph._edge_end`` semantics), or ``("", "")``."""
    return next(((key, _text(edge.get(key))) for key in keys if _text(edge.get(key))), ("", ""))


def edge_source(edge: dict[str, Any]) -> tuple[str, str]:
    return edge_end(edge, _SOURCE_KEYS)


def edge_target(edge: dict[str, Any]) -> tuple[str, str]:
    return edge_end(edge, _TARGET_KEYS)


def is_fragment_definition(definition: Any) -> bool:
    return isinstance(definition, dict) and _text(definition.get(EXECUTION_KIND_KEY)) == FRAGMENT_KIND


def is_marker(edge: Any) -> bool:
    return isinstance(edge, dict) and FRAGMENT_EDGES_KEY in edge


def is_composite_source(definition: Any) -> bool:
    if not is_phased_definition(definition):
        return False
    nodes, edges = definition.get("nodes") or [], definition.get("edges") or []
    return (any(isinstance(node, dict) and _text(node.get("type")) == NODE_FRAGMENT for node in nodes)
            or any(is_marker(edge) for edge in edges))


def _kinds(definition: dict[str, Any], key: str, errors: list[dict[str, str]]) -> frozenset[str]:
    raw = definition.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        errors.append(error(f"fragment_{key}", f"A fragment's {key} is a list of artefact kinds."))
        return frozenset()
    return frozenset(item.strip() for item in raw)


def _ports(definition: dict[str, Any], errors: list[dict[str, str]]) -> dict[str, FragmentPort]:
    raw = definition.get("ports")
    if not isinstance(raw, dict) or not raw:
        errors.append(error("fragment_ports", "A fragment declares its exits as ports (at least one)."))
        return {}
    ports: dict[str, FragmentPort] = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not re.match(PORT_NAME_RE, name):
            errors.append(error("fragment_port_invalid", f"Port '{name}' needs a lower-case name."))
            continue
        spec = spec if isinstance(spec, dict) else {}
        edge, accepts = _text(spec.get("edge")), _text(spec.get("accepts"))
        if edge not in PORT_EDGES or accepts not in PORT_ACCEPTS:
            errors.append(error("fragment_port_invalid", f"Port '{name}' takes an edge "
                                f"({', '.join(sorted(PORT_EDGES))}) and accepts one of "
                                f"{', '.join(sorted(PORT_ACCEPTS))}."))
            continue
        if edge == "loop" and accepts != "any":
            errors.append(error("fragment_port_invalid", f"Loop port '{name}' leads back to any earlier node "
                                                         "(accepts: any)."))
            continue
        ports[name] = FragmentPort(name, edge, accepts)
    return ports


def _nodes(definition: dict[str, Any], errors: list[dict[str, str]]) -> tuple[dict, ...]:
    raw = definition.get("nodes")
    if not isinstance(raw, list) or not raw:
        errors.append(error("fragment_nodes", "A fragment has at least one node."))
        return ()
    seen: set[str] = set()
    for node in raw:
        node_id = _text(node.get("id")) if isinstance(node, dict) else ""
        if not node_id or not isinstance(node.get("id"), str) or node["id"] != node_id:
            errors.append(error("fragment_nodes", "Every fragment node is an object with its own id."))
            continue
        kind = _text(node.get("type"))
        if node_id in seen:
            errors.append(error("fragment_id_collision", f"Fragment node id '{node_id}' is used twice."))
        seen.add(node_id)
        if kind == NODE_FRAGMENT:
            errors.append(error("fragment_nested", f"Node '{node_id}' references a fragment inside a fragment."))
        elif kind not in FRAGMENT_NODE_KINDS:
            errors.append(error("fragment_node_kind", f"Node '{node_id}' kind '{kind}' cannot be part of a fragment "
                                "(no start, outcome or pause: the composite owns them, reached through ports)."))
    return tuple(node for node in raw if isinstance(node, dict))


def _edges(definition: dict[str, Any], local: set[str], ports: dict[str, FragmentPort],
           errors: list[dict[str, str]]) -> tuple[dict, ...]:
    raw = definition.get("edges")
    if not isinstance(raw, list):
        errors.append(error("fragment_edges", "A fragment's edges are a list."))
        return ()
    seen: set[str] = set()
    for edge in raw:
        if not isinstance(edge, dict) or not _text(edge.get("id")):
            errors.append(error("fragment_edges", "Every fragment edge is an object with its own id."))
            continue
        edge_id = _text(edge["id"])
        if edge_id in seen:
            errors.append(error("fragment_id_collision", f"Fragment edge id '{edge_id}' is used twice."))
        seen.add(edge_id)
        if is_marker(edge):
            errors.append(error("fragment_nested", f"Edge '{edge_id}' splices a fragment inside a fragment."))
            continue
        if _text(edge.get("source_node_id")) not in local:
            errors.append(error("fragment_edge_source", f"Edge '{edge_id}' leaves a node outside the fragment."))
        has_target, port = bool(_text(edge.get("target_node_id"))), _text(edge.get("target_port"))
        if has_target == bool(port) or any(_text(edge.get(key)) for key in _TARGET_KEYS[1:] + _SOURCE_KEYS[1:]):
            errors.append(error("fragment_edge_target", f"Edge '{edge_id}' has exactly one of target_node_id (a "
                                                        "fragment node) or target_port (a declared port)."))
            continue
        if has_target and _text(edge["target_node_id"]) not in local:
            errors.append(error("fragment_edge_target", f"Edge '{edge_id}' leads to a node outside the fragment; an "
                                                        "exit goes through a port."))
        if port and port not in ports:
            errors.append(error("fragment_port_unknown", f"Edge '{edge_id}' exits through an undeclared port "
                                                         f"'{port}'."))
        elif port and (_text(edge.get("kind")) or "next") != ports[port].edge:
            errors.append(error("fragment_port_edge", f"Edge '{edge_id}' is a '{_text(edge.get('kind')) or 'next'}' "
                                                      f"edge; port '{port}' is a '{ports[port].edge}' port."))
    return tuple(edge for edge in raw if isinstance(edge, dict))


def parse_fragment(definition: dict) -> FragmentDefinition:
    """The fragment definition; :class:`FragmentError` with every structural refusal."""
    if not isinstance(definition, dict):
        raise FragmentError([error("fragment_kind", "A fragment definition is an object.")])
    errors: list[dict[str, str]] = []
    if not is_fragment_definition(definition):
        errors.append(error("fragment_kind", f"A fragment's execution_kind is '{FRAGMENT_KIND}'."))
    if definition.get("schema_version") != FRAGMENT_SCHEMA:
        errors.append(error("fragment_schema", f"A fragment's schema_version is '{FRAGMENT_SCHEMA}'."))
    for key in sorted(DEFINITION_LEVEL_KEYS & set(definition)):
        errors.append(error("fragment_definition_key", f"A fragment carries no '{key}': the composite owns it."))
    instance = definition.get("instance", INSTANCE_SINGLE)
    if instance not in (INSTANCE_SINGLE, INSTANCE_MANY):
        errors.append(error("fragment_instance", f"A fragment's instance is '{INSTANCE_SINGLE}' or "
                                                 f"'{INSTANCE_MANY}'."))
    ports = _ports(definition, errors)
    nodes = _nodes(definition, errors)
    local = {_text(node.get("id")) for node in nodes}
    edges = _edges(definition, local, ports, errors)
    entry = definition.get("entry")
    if not isinstance(entry, str) or entry not in local:
        errors.append(error("fragment_entry", "A fragment's entry names one of its nodes."))
    requires, provides = _kinds(definition, "requires", errors), _kinds(definition, "provides", errors)
    if errors:
        raise FragmentError(errors)
    return FragmentDefinition(entry=str(entry), ports=ports, requires=requires, provides=provides,
                              instance=str(instance), nodes=nodes, edges=edges, raw=definition)


def _ref(node: dict[str, Any], index: int, errors: list[dict[str, str]]) -> FragmentRef | None:
    node_id = _text(node.get("id"))
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    count = len(errors)
    key = config.get("fragment_key")
    if not isinstance(key, str) or not key.strip():
        errors.append(error("fragment_ref_invalid", f"Fragment reference '{node_id}' names no fragment_key."))
    checksum = config.get("fragment_checksum")
    if not isinstance(checksum, str) or not _CHECKSUM_RE.match(checksum):
        errors.append(error("fragment_pin_missing", f"Fragment reference '{node_id}' pins its fragment by a "
                                                    "sha256 checksum (fragment_checksum)."))
    version_id = config.get("fragment_version_id")
    if version_id is not None and (not isinstance(version_id, str) or not version_id.strip()):
        errors.append(error("fragment_pin_missing", f"Fragment reference '{node_id}': fragment_version_id is the "
                                                    "pinned version's id."))
    namespace = config.get("namespace", f"{node_id}.")
    if not isinstance(namespace, str) or not re.match(NAMESPACE_RE, namespace):
        errors.append(error("fragment_namespace", f"Fragment reference '{node_id}': the namespace is '' or a "
                                                  "lower-case name ending in '.'."))
    ports = config.get("ports")
    if not isinstance(ports, dict) or not all(isinstance(name, str) and isinstance(target, str) and target.strip()
                                              for name, target in ports.items()):
        errors.append(error("fragment_ref_invalid", f"Fragment reference '{node_id}' maps its ports to node ids."))
    if len(errors) > count:
        return None
    return FragmentRef(node_id=node_id, fragment_key=key.strip(), version_id=version_id, checksum=checksum,
                       namespace=namespace, ports={name: target.strip() for name, target in ports.items()},
                       index=index)


def fragment_refs(source: dict) -> list[FragmentRef]:
    """The reference nodes of a composite source, in source order; :class:`FragmentError` on a malformed one."""
    errors: list[dict[str, str]] = []
    refs: list[FragmentRef] = []
    for index, node in enumerate(source.get("nodes") or [] if isinstance(source, dict) else []):
        if isinstance(node, dict) and _text(node.get("type")) == NODE_FRAGMENT:
            if not _text(node.get("id")):
                errors.append(error("fragment_ref_invalid", f"The fragment reference at node {index} has no id."))
                continue
            ref = _ref(node, index, errors)
            if ref is not None:
                refs.append(ref)
    if errors:
        raise FragmentError(errors)
    return refs


__all__ = [
    "FRAGMENT_EDGES_KEY", "FRAGMENT_KIND", "FRAGMENT_NODE_KINDS", "FRAGMENT_SCHEMA", "INSTANCE_MANY",
    "INSTANCE_SINGLE", "MAX_NODE_ID", "NAMESPACE_RE", "NODE_FRAGMENT", "PORT_ACCEPTS", "PORT_EDGES",
    "FragmentDefinition", "FragmentError", "FragmentPort", "FragmentRef", "ResolvedFragment", "fragment_refs",
    "is_composite_source", "is_fragment_definition", "parse_fragment",
]
