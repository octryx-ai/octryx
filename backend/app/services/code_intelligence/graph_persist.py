"""Native persistence of a built code graph artifact into the code graph tables."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CodeGraphRepository,
    CodeGraphRun,
    CodeGraphStaleness,
)
from app.services.code_intelligence.graph_lifecycle import mark_previous_graph_rows_stale
from app.services.code_intelligence.graph_persist_chunks import _persist_chunk_rows
from app.services.code_intelligence.graph_persist_entities import (
    _persist_edge_rows,
    _persist_file_rows,
    _persist_node_rows,
    _persist_symbol_rows,
)
from app.services.code_intelligence.graph_persist_rows import (
    _persist_reference_rows,
    _persist_route_rows,
    _persist_snapshot_and_staleness_rows,
)
from app.services.code_intelligence.graph_persist_unresolved import _persist_unresolved_rows
from app.services.code_intelligence.storage_runtime import _coerce_dict, _coerce_list
from app.time_utils import utc_now_aware


async def _persist_code_graph_artifacts(
    *,
    db: AsyncSession,
    repository_id: str,
    repo_root: Path,
    snapshot: dict[str, Any],
    artifact: dict[str, Any],
    graph_trigger: str,
    sync_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact = _coerce_dict(artifact)
    persisted_payload = _load_persisted_payload(artifact)
    now = utc_now_aware()
    sync_plan = _coerce_dict(sync_plan)

    graph_repo = await _get_or_create_graph_repo(db, repository_id=repository_id)
    graph_run = await _start_graph_run(
        db, graph_repo=graph_repo, repository_id=repository_id, graph_trigger=graph_trigger, now=now
    )
    started_ms = time.perf_counter()
    scope = {"db": db, "graph_run": graph_run, "graph_repo": graph_repo, "repository_id": repository_id}
    file_lookup, source_node_count, counts = await _persist_graph_rows(
        **scope, repo_root=repo_root, snapshot=snapshot, persisted_payload=persisted_payload
    )
    _finish_graph_run(
        graph_run,
        artifact=artifact,
        counts=counts,
        started_ms=started_ms,
        source_node_count=source_node_count,
        sync_plan=sync_plan,
        file_lookup=file_lookup,
    )
    _persist_snapshot_and_staleness_rows(
        **scope,
        artifact=artifact,
        persisted_payload=persisted_payload,
        file_lookup=file_lookup,
        sync_plan=sync_plan,
    )
    _mark_graph_repo_built(graph_repo, graph_run=graph_run, file_lookup=file_lookup)
    # The graph itself is the source, read through the code-graph tools.
    await db.flush()
    await db.commit()

    return {
        **counts,
        "graph_repo_id": graph_repo.id,
        "graph_run_id": graph_run.id,
        "sync": graph_run.run_metadata.get("sync", {}),
    }


async def _persist_graph_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    repo_root: Path,
    snapshot: dict[str, Any],
    persisted_payload: dict[str, Any],
) -> tuple[dict[str, Any], int, dict[str, int]]:
    """Write every row of the run; returns the file lookup, the source node count and the row counts."""
    nodes_to_persist = _coerce_list(persisted_payload.get("nodes"))
    edges_to_persist = _coerce_list(persisted_payload.get("edges"))
    unresolved_to_persist = _coerce_list(persisted_payload.get("unresolved_references"))
    scope = {"db": db, "graph_run": graph_run, "graph_repo": graph_repo}
    file_lookup, persisted_files = _persist_file_rows(
        **scope,
        repo_root=repo_root,
        snapshot=snapshot,
        file_node_metadata_by_path=_file_node_metadata_by_path(nodes_to_persist),
    )
    graph_nodes = await _persist_node_rows(**scope, nodes_to_persist=nodes_to_persist, file_lookup=file_lookup)
    graph_symbols = await _persist_symbol_rows(**scope, repository_id=repository_id, graph_nodes=graph_nodes)
    edge_entities, unresolved_edges = await _persist_edge_rows(
        **scope, edges_to_persist=edges_to_persist, graph_nodes=graph_nodes
    )
    _persist_derived_rows(
        **scope,
        repository_id=repository_id,
        repo_root=repo_root,
        file_lookup=file_lookup,
        graph_nodes=graph_nodes,
        graph_symbols=graph_symbols,
        edge_entities=edge_entities,
    )
    unresolved_references = _persist_unresolved_rows(
        **scope,
        repository_id=repository_id,
        file_lookup=file_lookup,
        unresolved_to_persist=unresolved_to_persist,
        unresolved_edges=unresolved_edges,
    )
    counts = {
        "persisted_files": persisted_files,
        "persisted_nodes": len(graph_nodes),
        "persisted_edges": len(edge_entities),
        "unresolved_references": unresolved_references,
    }
    return file_lookup, len(graph_nodes), counts


def _load_persisted_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    persisted_payload = _coerce_dict(artifact.get("graph_payload"))
    if not persisted_payload:
        graph_path = str(artifact.get("graph_path") or "").strip()
        if graph_path:
            try:
                persisted_payload = json.loads(Path(graph_path).read_text(encoding="utf-8"))
            except Exception:
                persisted_payload = {}
    return _coerce_dict(persisted_payload)


def _file_node_metadata_by_path(nodes_to_persist: list[Any]) -> dict[str, dict[str, Any]]:
    file_node_metadata_by_path: dict[str, dict[str, Any]] = {}
    for item in nodes_to_persist:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "file":
            continue
        path = str(item.get("path") or item.get("label") or "").strip()
        if path:
            file_node_metadata_by_path[path] = _coerce_dict(item.get("metadata"))
    return file_node_metadata_by_path


async def _get_or_create_graph_repo(db: AsyncSession, *, repository_id: str) -> CodeGraphRepository:
    graph_repo_result = await db.execute(
        select(CodeGraphRepository).where(CodeGraphRepository.code_repository_id == repository_id)
    )
    graph_repo = graph_repo_result.scalar_one_or_none()
    if graph_repo is None:
        graph_repo = CodeGraphRepository(
            id=str(uuid4()),
            code_repository_id=repository_id,
            graph_backend="code_graph",
            graph_schema_version="v1",
            indexing_mode="full",
            backend_metadata={"backend": "code_graph", "source": "native"},
            config_json={},
            staleness_state="stale",
        )
        db.add(graph_repo)
        await db.flush()
    return graph_repo


async def _start_graph_run(
    db: AsyncSession,
    *,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    graph_trigger: str,
    now: Any,
) -> CodeGraphRun:
    await db.execute(
        update(CodeGraphRun)
        .where(CodeGraphRun.graph_repository_id == graph_repo.id)
        .values(is_stale=True, staleness_reason="superseded_by_new_index_run")
    )
    await mark_previous_graph_rows_stale(db=db, graph_repo_id=graph_repo.id)
    await db.execute(delete(CodeGraphStaleness).where(CodeGraphStaleness.graph_repository_id == graph_repo.id))

    graph_run = CodeGraphRun(
        id=str(uuid4()),
        graph_repository_id=graph_repo.id,
        code_repository_id=repository_id,
        backend="code_graph",
        trigger=graph_trigger,
        status="running",
        started_at=now,
        run_metadata={},
    )
    graph_repo.latest_run_id = graph_run.id
    graph_repo.staleness_state = "building"
    db.add(graph_run)
    db.add(graph_repo)
    await db.flush()
    return graph_run


def _persist_derived_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    repo_root: Path,
    file_lookup: dict[str, Any],
    graph_nodes: dict[str, Any],
    graph_symbols: dict[str, Any],
    edge_entities: list[tuple[dict[str, Any], Any]],
) -> None:
    scope = {"db": db, "graph_run": graph_run, "graph_repo": graph_repo, "repository_id": repository_id}
    _persist_reference_rows(
        **scope, graph_nodes=graph_nodes, graph_symbols=graph_symbols, edge_entities=edge_entities
    )
    _persist_route_rows(
        **scope,
        file_lookup=file_lookup,
        graph_nodes=graph_nodes,
        graph_symbols=graph_symbols,
        edge_entities=edge_entities,
    )
    _persist_chunk_rows(**scope, repo_root=repo_root, file_lookup=file_lookup, graph_symbols=graph_symbols)


def _finish_graph_run(
    graph_run: CodeGraphRun,
    *,
    artifact: dict[str, Any],
    counts: dict[str, int],
    started_ms: float,
    source_node_count: int,
    sync_plan: dict[str, Any],
    file_lookup: dict[str, Any],
) -> None:
    graph_run.status = "ready"
    graph_run.finished_at = utc_now_aware()
    graph_run.duration_ms = int((time.perf_counter() - started_ms) * 1000)
    graph_run.file_count = counts["persisted_files"]
    graph_run.node_count = counts["persisted_nodes"]
    graph_run.edge_count = counts["persisted_edges"]
    graph_run.unresolved_reference_count = counts["unresolved_references"]
    graph_run.run_metadata = {
        "artifact": {
            "backend": "code_graph",
            "path": str(artifact.get("graph_path") or ""),
            "report_path": str(artifact.get("report_path") or ""),
        },
        "persisted_nodes": counts["persisted_nodes"],
        "persisted_edges": counts["persisted_edges"],
        "persisted_files": counts["persisted_files"],
        "unresolved_references": counts["unresolved_references"],
        "source_node_count": source_node_count,
        "sync": {
            **sync_plan,
            "files_errored": sum(1 for item in file_lookup.values() if item.parse_error),
            "graph_rows_changed": sum(counts.values()),
        },
    }


def _mark_graph_repo_built(
    graph_repo: CodeGraphRepository, *, graph_run: CodeGraphRun, file_lookup: dict[str, Any]
) -> None:
    graph_repo.staleness_state = "degraded" if any(item.parse_error for item in file_lookup.values()) else "fresh"
    graph_repo.latest_run_id = graph_run.id
    graph_repo.backend_metadata = {
        **(graph_repo.backend_metadata or {}),
        "latest_sync": graph_run.run_metadata.get("sync", {}),
        "pending_sync": {},
    }
