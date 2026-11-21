"""Entity-graph visualization payloads for the admin panel.

Builds bounded subgraphs of the REAL knowledge graph (``knowledge_graph_nodes``
/ ``knowledge_graph_edges`` — the gold entity layer), not the medallion
provenance relations. Three entry modes:

- default: the highest-degree nodes (the connective skeleton),
- query: nodes that really match the query (keyword/alias hit or a semantic
  score above the threshold) as seeds, plus their neighborhoods; the payload
  names the matches (``match_ids``, ``stats.matched_nodes``) so the UI can
  highlight them or say that nothing matched,
- focus: BFS neighborhood around one node.

With a ``project_id`` every node, edge and total is scoped to that project plus
the instance-global (``project_id IS NULL``) layer.
"""

from __future__ import annotations

from .detail import get_entity_node_detail
from .graph import MAX_NODES, MAX_QUERY_MATCHES, build_entity_graph

__all__ = ["MAX_NODES", "MAX_QUERY_MATCHES", "build_entity_graph", "get_entity_node_detail"]
