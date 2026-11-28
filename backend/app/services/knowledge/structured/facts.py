"""What a rule-based extractor returns: typed nodes and edges, each cited."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

MAX_LABEL_CHARS = 300
MAX_KEY_CHARS = 512
MAX_TEXT_PROPERTY_CHARS = 400


def node_id(node_type: str, node_key: str) -> str:
    return hashlib.sha256(f"{node_type}|{node_key}".encode()).hexdigest()


def clip(text: str, limit: int = MAX_TEXT_PROPERTY_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class SpanInput:
    ordinal: int
    text: str
    kind: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None

    @property
    def leaf_heading(self) -> str | None:
        return self.section_path[-1] if self.section_path else None


@dataclass(frozen=True, slots=True)
class SpanRef:
    span_ordinal: int
    line: int | None = None


@dataclass(frozen=True, slots=True)
class NodeRef:
    node_type: str
    node_key: str

    @property
    def id(self) -> str:
        return node_id(self.node_type, self.node_key)


@dataclass(slots=True)
class NodeFact:
    ref: NodeRef
    label: str
    properties: dict[str, Any] = field(default_factory=dict)
    cite: SpanRef | None = None


@dataclass(slots=True)
class EdgeFact:
    edge_type: str
    source: NodeRef
    target: NodeRef
    cites: tuple[SpanRef, ...]
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Extraction:
    nodes: dict[NodeRef, NodeFact] = field(default_factory=dict)
    edges: dict[tuple[str, NodeRef, NodeRef], EdgeFact] = field(default_factory=dict)
    warnings: Counter = field(default_factory=Counter)

    def node(self, node_type: str, node_key: str, label: str, cite: SpanRef | None = None, **properties) -> NodeRef:
        ref = NodeRef(node_type, node_key[:MAX_KEY_CHARS])
        if ref not in self.nodes:
            self.nodes[ref] = NodeFact(ref, clip(label, MAX_LABEL_CHARS), properties, cite)
        return ref

    def edge(self, edge_type: str, source: NodeRef, target: NodeRef, cite: SpanRef, **properties) -> None:
        if source == target:
            return
        key = (edge_type, source, target)
        if key not in self.edges:
            self.edges[key] = EdgeFact(edge_type, source, target, (cite,), properties)

    def warn(self, token: str, count: int = 1) -> None:
        self.warnings[token] += count


__all__ = [
    "EdgeFact",
    "Extraction",
    "NodeFact",
    "NodeRef",
    "SpanInput",
    "SpanRef",
    "clip",
    "node_id",
]
