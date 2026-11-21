"""Status derivation and serializers for the code graph admin health snapshot."""

from __future__ import annotations

from typing import Any

from app.models import CodeGraphRepository, CodeGraphRun, CodeRepository
from app.services.code_intelligence.mirror import mirror_status
from app.services.code_intelligence.storage_runtime import _coerce_dict


def _empty_status(
    repo: CodeRepository,
    status: str,
    *,
    graph_repo: CodeGraphRepository | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "repository_id": repo.id,
        "project_id": repo.project_id,
        "graph_repository_id": graph_repo.id if graph_repo else None,
        "backend": graph_repo.graph_backend if graph_repo else repo.graph_backend,
        "schema_version": graph_repo.graph_schema_version if graph_repo else None,
        "indexing_mode": graph_repo.indexing_mode if graph_repo else None,
        "staleness_state": graph_repo.staleness_state if graph_repo else "unknown",
        "capabilities": _coerce_dict(repo.capabilities_json).get("graph") or {},
        "mirror": mirror_status(repo),
        "latest_run": None,
        "run_history": [],
        "summary": _zero_summary(),
        "sync": {"state": status, "warnings": [], "summary": {}},
        "stale_files": [],
        "parse_errors": [],
        "metrics": {
            "latest_duration_ms": None,
            "latest_file_count": 0,
            "latest_node_count": 0,
            "latest_edge_count": 0,
            "latest_unresolved_reference_count": 0,
            "stale_file_count": 0,
            "parse_error_count": 0,
        },
    }

def _derive_admin_status(
    *,
    graph_repo: CodeGraphRepository,
    latest_run: CodeGraphRun,
    sync_state: dict[str, Any],
    stale_count: int,
) -> str:
    run_status = str(latest_run.status or "").strip().lower()
    if run_status in {"error", "failed"}:
        return "error"
    if run_status in {"running", "queued"}:
        return run_status
    if (
        latest_run.is_stale
        or graph_repo.staleness_state == "stale"
        or sync_state.get("state") == "stale"
        or stale_count
    ):
        return "stale"
    return "ready" if run_status == "ready" else (run_status or "unknown")


def _serialize_graph_run(run: CodeGraphRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "repository_id": run.code_repository_id,
        "graph_repository_id": run.graph_repository_id,
        "status": run.status,
        "trigger": run.trigger,
        "backend": run.backend,
        "file_count": run.file_count,
        "node_count": run.node_count,
        "edge_count": run.edge_count,
        "unresolved_reference_count": run.unresolved_reference_count,
        "duration_ms": run.duration_ms,
        "is_stale": bool(run.is_stale),
        "staleness_reason": run.staleness_reason,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _zero_summary() -> dict[str, Any]:
    return {
        "file_count": 0,
        "node_count": 0,
        "edge_count": 0,
        "symbol_count": 0,
        "reference_count": 0,
        "route_count": 0,
        "chunk_count": 0,
        "unresolved_reference_count": 0,
        "language_distribution": {},
    }
