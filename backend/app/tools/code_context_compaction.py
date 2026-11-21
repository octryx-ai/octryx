"""Code Intelligence-owned model context; full originals remain in tool artifacts."""

from __future__ import annotations

import json
from typing import Any

from ..services.token_estimation import estimate_serialized_tokens

MAX_PACKET_BYTES = 6000
MAX_PACKET_ESTIMATED_TOKENS = 1600
NODE_FIELDS = ("id", "name", "node_type", "path", "line_start", "line_end", "confidence", "is_stale")
CHUNK_FIELDS = ("path", "line_start", "line_end", "content")
EDGE_FIELDS = ("source_node_id", "target_node_id", "relation", "confidence")


def _fields(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def _fits(packet: dict[str, Any]) -> bool:
    text = json.dumps(packet, ensure_ascii=False, default=str)
    return (len(text.encode("utf-8")) <= MAX_PACKET_BYTES - 32
            and estimate_serialized_tokens(packet) <= MAX_PACKET_ESTIMATED_TOKENS - 16)


def compact_code_context(result: dict[str, Any]) -> dict[str, Any]:
    """Select whole records, preserving locations and explicit gaps without generated summaries."""
    graph = _fields(result.get("graph"), ("run_id", "commit_hash", "backend", "status", "is_stale", "staleness_state"))
    nodes = [item for item in result.get("context_nodes", []) if isinstance(item, dict)]
    edges = [item for item in result.get("context_edges", []) if isinstance(item, dict)]
    chunks = [item["source_chunk"] for item in nodes if isinstance(item.get("source_chunk"), dict)]
    for file in result.get("context_files", []):
        if isinstance(file, dict):
            chunks.extend(item for item in file.get("source_chunks", []) if isinstance(item, dict))
    # Account for omitted retrieval candidates as well as compaction omissions.
    selection_budget = result.get("budget") or {}
    packet: dict[str, Any] = {
        "context_format": "cited_code_packet",
        "status": "truncated" if result.get("status", "ready") == "ready" else result.get("status"),
        "repository": _fields(result.get("repository"), ("id",)),
        "graph": graph,
        "start_node": _fields(result.get("start_node"), NODE_FIELDS),
        "context_nodes": [], "source_chunks": [], "context_edges": [],
        "omitted": {"nodes": len(nodes) + int(selection_budget.get("omitted_nodes") or 0),
                    "metadata": 0, "chunks": len(chunks),
                    "edges": len(edges) + int(selection_budget.get("omitted_edges") or 0)},
        "truncated": True,
        "agent_guidance": [
            "Cite source paths and line ranges. Read missing or stale source before relying on it.",
            "Expand with code_node or code_context for a specific symbol; full detail is in the tool artifact.",
        ],
        "model_budget": {"max_bytes": MAX_PACKET_BYTES, "max_estimated_tokens": MAX_PACKET_ESTIMATED_TOKENS},
    }
    # Oversized identifiers/diagnostics must not bypass the complete-packet limit.
    for key in ("start_node", "graph", "repository"):
        if not _fits(packet):
            packet[key] = {}
            packet["omitted"]["metadata"] += 1
    if not packet["repository"].get("id") or not packet["graph"].get("run_id"):
        # Evidence without its repository and index identity is not usable model context.
        packet["status"] = (
            result.get("status") if result.get("status") in {"graph_not_indexed", "node_not_found"}
            else "needs_more_context"
        )
        return packet
    unique_chunks: dict[str, dict[str, Any]] = {}
    for item in chunks:
        chunk = _fields(item, CHUNK_FIELDS)
        key = json.dumps(chunk, sort_keys=True, ensure_ascii=False, default=str)
        unique_chunks.setdefault(key, chunk)
    packet["omitted"]["chunks"] = len(unique_chunks)
    for chunk in unique_chunks.values():
        packet["source_chunks"].append(chunk)
        if not _fits(packet):
            packet["source_chunks"].pop()
            continue
        packet["omitted"]["chunks"] -= 1
    selected_ids: set[str] = set()
    for item in nodes:
        node = _fields(item.get("node"), NODE_FIELDS)
        if not node:
            continue
        packet["context_nodes"].append({"node": node})
        if not _fits(packet):
            packet["context_nodes"].pop()
            continue
        selected_ids.add(str(node.get("id") or ""))
        packet["omitted"]["nodes"] -= 1
    for item in edges:
        edge = _fields(item.get("edge", item), EDGE_FIELDS)
        if not {str(edge.get("source_node_id") or ""), str(edge.get("target_node_id") or "")} <= selected_ids:
            continue
        packet["context_edges"].append(edge)
        if not _fits(packet):
            packet["context_edges"].pop()
            continue
        packet["omitted"]["edges"] -= 1
    packet["truncated"] = bool(result.get("truncated") or any(packet["omitted"].values()))
    if not packet["truncated"] and result.get("status", "ready") == "ready":
        packet["status"] = "ready"
    return packet


def register_result_compactors() -> None:
    from ..agent.engine.messages._tool_compaction_registry import register_tool_result_compactor

    for tool_name in ("code_context", "code_explore"):
        register_tool_result_compactor(tool_name, compact_code_context)
