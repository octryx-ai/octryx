"""The value types the structured-graph writers hand back and take in."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class WriteCounts:
    nodes: int = 0
    edges: int = 0
    removed_nodes: int = 0
    removed_edges: int = 0


@dataclass(slots=True)
class LinkEdge:
    edge_type: str
    source_id: str
    target_id: str
    citations: list[tuple[str, int, int | None]]
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return hashlib.sha256(f"link|{self.edge_type}|{self.source_id}|{self.target_id}".encode()).hexdigest()


__all__ = ["LinkEdge", "WriteCounts"]
