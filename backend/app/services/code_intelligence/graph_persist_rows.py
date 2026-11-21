"""Row builders that project a persisted code graph run into its derived tables."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CodeGraphEdge,
    CodeGraphFile,
    CodeGraphNode,
    CodeGraphReference,
    CodeGraphRepository,
    CodeGraphRoute,
    CodeGraphRun,
    CodeGraphSnapshot,
    CodeGraphStaleness,
    CodeGraphSymbol,
)
from app.services.code_intelligence.storage_runtime import _coerce_dict, _coerce_list


def _persist_reference_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    graph_nodes: dict[str, CodeGraphNode],
    graph_symbols: dict[str, CodeGraphSymbol],
    edge_entities: list[tuple[dict[str, Any], CodeGraphEdge]],
) -> None:
    reference_relations = {"calls", "references", "imports", "routes_to", "tested_by"}
    seen_reference_keys: set[tuple[str | None, str, str, int | None]] = set()
    for item, edge in edge_entities:
        relation = str(item.get("kind") or edge.relation or "").strip()
        if relation not in reference_relations:
            continue
        source_external_id = str(item.get("source") or "").strip()
        target_external_id = str(item.get("target") or "").strip()
        source_node = graph_nodes.get(source_external_id)
        source_symbol = graph_symbols.get(source_external_id)
        target_symbol = graph_symbols.get(target_external_id)
        metadata = _coerce_dict(item.get("metadata"))
        line_start = int(metadata.get("line") or 0) or None
        reference_name = str(item.get("label") or (target_symbol.name if target_symbol else relation))
        identity_key = (source_node.source_file_id if source_node else None, reference_name, relation, line_start)
        if identity_key in seen_reference_keys:
            continue
        seen_reference_keys.add(identity_key)
        db.add(
            CodeGraphReference(
                id=str(uuid4()),
                run_id=graph_run.id,
                graph_repository_id=graph_repo.id,
                code_repository_id=repository_id,
                source_file_id=source_node.source_file_id if source_node else None,
                source_symbol_id=source_symbol.id if source_symbol else None,
                target_symbol_id=target_symbol.id if target_symbol else None,
                edge_id=edge.id,
                reference_name=reference_name,
                reference_kind=relation,
                status="resolved",
                candidates_json=[target_symbol.stable_symbol_id] if target_symbol else [],
                line_start=line_start,
                confidence=edge.confidence,
                reference_metadata={"edge_id": edge.id, **metadata},
                is_current=True,
            )
        )


def _persist_route_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    file_lookup: dict[str, CodeGraphFile],
    graph_nodes: dict[str, CodeGraphNode],
    graph_symbols: dict[str, CodeGraphSymbol],
    edge_entities: list[tuple[dict[str, Any], CodeGraphEdge]],
) -> None:
    for item, _edge in edge_entities:
        if str(item.get("kind") or "") != "routes_to":
            continue
        route_node = graph_nodes.get(str(item.get("source") or ""))
        handler_symbol = graph_symbols.get(str(item.get("target") or ""))
        if route_node is None:
            continue
        metadata = _coerce_dict(route_node.node_metadata)
        framework = str(metadata.get("framework") or "").strip()
        method = str(metadata.get("method") or "").strip()
        route_path = str(metadata.get("route_path") or "").strip()
        if not framework or not method or not route_path:
            continue
        db.add(
            CodeGraphRoute(
                id=str(uuid4()),
                run_id=graph_run.id,
                graph_repository_id=graph_repo.id,
                code_repository_id=repository_id,
                router_file_id=file_lookup.get(route_node.path or "").id if route_node.path in file_lookup else None,
                route_node_id=route_node.id,
                handler_symbol_id=handler_symbol.id if handler_symbol else None,
                method=method,
                route_path=route_path,
                framework=framework,
                line_start=route_node.line_start,
                line_end=route_node.line_end,
                confidence=route_node.confidence,
                route_metadata=metadata,
                is_current=True,
            )
        )


def _persist_snapshot_and_staleness_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    artifact: dict[str, Any],
    persisted_payload: dict[str, Any],
    file_lookup: dict[str, CodeGraphFile],
    sync_plan: dict[str, Any],
) -> None:
    payload_text = json.dumps(persisted_payload, sort_keys=True)
    db.add(
        CodeGraphSnapshot(
            id=str(uuid4()),
            run_id=graph_run.id,
            graph_repository_id=graph_repo.id,
            code_repository_id=repository_id,
            snapshot_kind="index",
            artifact_path=str(artifact.get("graph_path") or "") or None,
            content_hash=hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
            file_count=int(graph_run.file_count or 0),
            symbol_count=int(graph_run.node_count or 0),
            edge_count=int(graph_run.edge_count or 0),
            snapshot_metadata={
                "backend": "code_graph",
                "report_path": str(artifact.get("report_path") or ""),
            },
        )
    )
    _add_staleness_rows(
        db=db,
        graph_run=graph_run,
        graph_repo=graph_repo,
        repository_id=repository_id,
        file_lookup=file_lookup,
        sync_plan=sync_plan,
    )


def _add_staleness_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    file_lookup: dict[str, CodeGraphFile],
    sync_plan: dict[str, Any],
) -> None:
    for graph_file in file_lookup.values():
        db.add(
            CodeGraphStaleness(
                id=str(uuid4()),
                graph_repository_id=graph_repo.id,
                code_repository_id=repository_id,
                run_id=graph_run.id,
                file_path=graph_file.file_path,
                observed_hash=graph_file.file_hash,
                observed_mtime_ns=graph_file.mtime_ns,
                indexed_hash=graph_file.file_hash,
                indexed_mtime_ns=graph_file.mtime_ns,
                status="error" if graph_file.parse_error else "fresh",
                reason=graph_file.parse_error,
                staleness_metadata={"source": "index_run"},
            )
        )
    for deleted_path in _coerce_list(sync_plan.get("deleted_paths")):
        file_path = str(deleted_path or "").strip()
        if not file_path:
            continue
        db.add(
            CodeGraphStaleness(
                id=str(uuid4()),
                graph_repository_id=graph_repo.id,
                code_repository_id=repository_id,
                run_id=graph_run.id,
                file_path=file_path,
                status="deleted",
                reason="file_deleted_since_previous_graph_run",
                staleness_metadata={"source": "index_run", "status": "deleted"},
            )
        )


def _unresolved_reference_projection(
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    source_file: CodeGraphFile | None,
    item: dict[str, Any],
) -> CodeGraphReference:
    line = int(item.get("line") or 0) or None
    return CodeGraphReference(
        id=str(uuid4()),
        run_id=graph_run.id,
        graph_repository_id=graph_repo.id,
        code_repository_id=repository_id,
        source_file_id=source_file.id if source_file else None,
        reference_name=str(item.get("symbol_text") or ""),
        reference_kind=str(item.get("reference_kind") or "reference"),
        status="unresolved",
        candidates_json=[],
        line_start=line,
        line_end=line,
        confidence="AMBIGUOUS",
        reference_metadata={"unresolved_reason": str(item.get("unresolved_reason") or "unresolved_reference")},
        is_current=True,
    )
