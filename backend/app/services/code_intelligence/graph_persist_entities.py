"""File, node, symbol and edge rows of a persisted code graph run."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CodeGraphEdge,
    CodeGraphFile,
    CodeGraphNode,
    CodeGraphRepository,
    CodeGraphRun,
    CodeGraphSymbol,
)
from app.services.code_intelligence.storage_runtime import _coerce_dict, _coerce_list


def _persist_file_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repo_root: Path,
    snapshot: dict[str, Any],
    file_node_metadata_by_path: dict[str, dict[str, Any]],
) -> tuple[dict[str, CodeGraphFile], int]:
    persisted_files = 0
    file_lookup: dict[str, CodeGraphFile] = {}
    for item in _coerce_list(snapshot.get("files")):
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("path") or "").strip()
        if not file_path:
            continue
        file_size = int(item.get("size_bytes") or 0)
        file_metadata = {
            "generated_from": "snapshot",
            **file_node_metadata_by_path.get(file_path, {}),
        }
        graph_file = CodeGraphFile(
            id=str(uuid4()),
            run_id=graph_run.id,
            graph_repository_id=graph_repo.id,
            file_path=file_path,
            language=str(item.get("language") or "").strip() or "unknown",
            size_bytes=file_size,
            line_count=int(item.get("line_count") or 0),
            is_binary=False,
            is_current=True,
            file_metadata=file_metadata,
        )
        parse_error = str(file_metadata.get("parse_error") or "").strip()
        if parse_error:
            graph_file.parse_error = parse_error
        _stamp_file_checksum(graph_file, absolute_path=repo_root / file_path, file_size=file_size)
        db.add(graph_file)
        file_lookup[file_path] = graph_file
        persisted_files += 1
    return file_lookup, persisted_files


def _stamp_file_checksum(graph_file: CodeGraphFile, *, absolute_path: Path, file_size: int) -> None:
    try:
        stat = absolute_path.stat()
        graph_file.mtime_ns = int(stat.st_mtime_ns)
        if not file_size:
            graph_file.size_bytes = int(stat.st_size)
        raw = absolute_path.read_bytes()
        graph_file.file_hash = hashlib.sha256(raw).hexdigest()
        graph_file.file_metadata["file_hash_algo"] = "sha256"
        if len(raw) > 256 * 1024:
            graph_file.file_metadata["truncated_checksum"] = False
        del raw
    except (FileNotFoundError, OSError):
        graph_file.parse_error = graph_file.parse_error or "source_file_unavailable"


async def _persist_node_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    nodes_to_persist: list[Any],
    file_lookup: dict[str, CodeGraphFile],
) -> dict[str, CodeGraphNode]:
    graph_nodes: dict[str, CodeGraphNode] = {}
    for item in nodes_to_persist:
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("id") or "").strip()
        if not external_id:
            continue
        if external_id in graph_nodes:
            continue
        kind = str(item.get("kind") or "").strip()
        label = str(item.get("label") or "").strip()
        path = str(item.get("path") or "").strip() or (label if kind == "file" else "")
        graph_node = CodeGraphNode(
            id=str(uuid4()),
            run_id=graph_run.id,
            graph_repository_id=graph_repo.id,
            external_id=external_id,
            node_type=kind or "unknown",
            name=label or external_id,
            language=str(item.get("language") or "").strip() or "unknown",
            line_start=int(item.get("line") or item.get("line_start") or 0) or None,
            line_end=int(item.get("line_end") or item.get("line") or 0) or None,
            path=path or None,
            signature=str(item.get("signature") or item.get("symbol_kind") or "").strip() or None,
            confidence=str(item.get("confidence") or "EXTRACTED").strip() or "EXTRACTED",
            is_current=True,
            node_metadata={
                "source": "native_extractor",
                **_coerce_dict(item.get("metadata")),
                **({"qualified_name": item.get("qualified_name")} if item.get("qualified_name") else {}),
                **({"parent_external_id": item.get("parent_id")} if item.get("parent_id") else {}),
            },
        )
        if path:
            graph_node.source_file = file_lookup.get(path)
        db.add(graph_node)
        graph_nodes[external_id] = graph_node
    await db.flush()
    return graph_nodes


async def _persist_symbol_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    graph_nodes: dict[str, CodeGraphNode],
) -> dict[str, CodeGraphSymbol]:
    graph_symbols: dict[str, CodeGraphSymbol] = {}
    pending_symbol_parents: list[tuple[CodeGraphSymbol, str]] = []
    for external_id, graph_node in graph_nodes.items():
        if graph_node.node_type in {"file", "route"}:
            continue
        metadata = _coerce_dict(graph_node.node_metadata)
        symbol = CodeGraphSymbol(
            id=str(uuid4()),
            run_id=graph_run.id,
            graph_repository_id=graph_repo.id,
            code_repository_id=repository_id,
            source_file_id=graph_node.source_file_id,
            node_id=graph_node.id,
            stable_symbol_id=external_id,
            kind=graph_node.node_type,
            name=graph_node.name,
            qualified_name=str(metadata.get("qualified_name") or graph_node.name),
            signature=graph_node.signature,
            visibility=str(metadata.get("visibility") or "") or None,
            is_exported=bool(metadata.get("is_exported") or False),
            is_static=bool(metadata.get("is_static") or False),
            is_async=bool(metadata.get("is_async") or graph_node.node_type == "async_function"),
            line_start=graph_node.line_start,
            line_end=graph_node.line_end,
            extraction_backend=str(metadata.get("extractor") or "native"),
            confidence=graph_node.confidence,
            symbol_metadata=metadata,
            is_current=True,
        )
        parent_external_id = str(metadata.get("parent_external_id") or "").strip()
        if parent_external_id:
            pending_symbol_parents.append((symbol, parent_external_id))
        db.add(symbol)
        graph_symbols[external_id] = symbol
    await db.flush()
    for symbol, parent_external_id in pending_symbol_parents:
        parent = graph_symbols.get(parent_external_id)
        if parent:
            symbol.parent_symbol_id = parent.id
    return graph_symbols


async def _persist_edge_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    edges_to_persist: list[Any],
    graph_nodes: dict[str, CodeGraphNode],
) -> tuple[list[tuple[dict[str, Any], CodeGraphEdge]], list[tuple[str, int, str, str]]]:
    unresolved_references_entries: list[tuple[str, int, str, str]] = []
    edge_entities: list[tuple[dict[str, Any], CodeGraphEdge]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for item in edges_to_persist:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        relation = str(item.get("kind") or "uses").strip() or "uses"
        label = str(item.get("label") or "").strip()
        edge_key = (source, target, relation)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        source_node = graph_nodes.get(source)
        target_node = graph_nodes.get(target)
        if not source_node or not target_node:
            unresolved_references_entries.append((label, 0, relation, source))
            continue
        edge = CodeGraphEdge(
            id=str(uuid4()),
            run_id=graph_run.id,
            graph_repository_id=graph_repo.id,
            source_node_id=source_node.id,
            target_node_id=target_node.id,
            relation=relation,
            confidence=str(item.get("confidence") or "EXTRACTED").strip() or "EXTRACTED",
            is_directed=True,
            is_current=True,
            edge_metadata={"label": label, **_coerce_dict(item.get("metadata"))},
        )
        db.add(edge)
        edge_entities.append((item, edge))
    await db.flush()
    return edge_entities, unresolved_references_entries
