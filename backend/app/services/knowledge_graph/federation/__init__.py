"""Hub-and-spoke federation for the entity knowledge graph (P8).

A hub instance exports a bounded subgraph as a portable, signed package
(nodes keyed by ``node_type``+``node_key`` with their aliases and claims, plus
the edges among them — no instance-local ids). A team instance imports it as
instance-global knowledge (``project_id`` NULL, ``trust_level`` "federated");
identity resolution happens through the alias table, so a federated person or
component merges deterministically with its local counterpart, exactly like a
local cross-connector ingest.

Signing reuses the engineering-knowledge federation primitives (deterministic
HMAC over canonical JSON) — same trust mechanics, one key contract. Keys are
always passed in explicitly by the caller; there is no default key.
"""

from __future__ import annotations

from .export import export_entity_graph_package
from .importer import _resolve_target_scope, import_entity_graph_package
from .package import (
    ENTITY_GRAPH_PACKAGE_FORMAT,
    FEDERATED_TRUST_LEVEL,
    MAX_EXPORT_NODES,
    EntityGraphPackageError,
    _node_ref,
    sign_entity_graph_package,
    verify_entity_graph_package,
)

__all__ = [
    "ENTITY_GRAPH_PACKAGE_FORMAT",
    "FEDERATED_TRUST_LEVEL",
    "MAX_EXPORT_NODES",
    "EntityGraphPackageError",
    "_node_ref",
    "_resolve_target_scope",
    "export_entity_graph_package",
    "import_entity_graph_package",
    "sign_entity_graph_package",
    "verify_entity_graph_package",
]
