"""Admin-facing health snapshots for native code graph repositories."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeGraphRepository, CodeGraphRun, CodeRepository
from app.services.code_intelligence.graph_admin_loaders import (
    _latest_run,
    _load_graph_summary,
    _load_parse_errors,
    _load_run_history,
    _load_stale_files,
    _load_sync_state,
)
from app.services.code_intelligence.graph_admin_serializers import (
    _derive_admin_status,
    _empty_status,
    _serialize_graph_run,
)
from app.services.code_intelligence.mirror import mirror_status
from app.services.code_intelligence.storage_runtime import _coerce_dict
from app.services.project_resource_policy import require_repository_operation


async def get_code_graph_admin_status(
    db: AsyncSession,
    *,
    repository_id: str,
    project_id: str | None = None,
    run_limit: int = 5,
    stale_limit: int = 10,
    error_limit: int = 10,
) -> dict[str, Any]:
    repo = await _load_repository(db, repository_id=repository_id, project_id=project_id)
    return await get_code_graph_admin_status_for_repository(
        db,
        repo=repo,
        run_limit=run_limit,
        stale_limit=stale_limit,
        error_limit=error_limit,
    )


async def get_code_graph_admin_status_for_repository(
    db: AsyncSession,
    *,
    repo: CodeRepository,
    run_limit: int = 5,
    stale_limit: int = 10,
    error_limit: int = 10,
) -> dict[str, Any]:
    require_repository_operation(repo, "read")
    graph_repo = (
        await db.execute(select(CodeGraphRepository).where(CodeGraphRepository.code_repository_id == repo.id))
    ).scalar_one_or_none()
    if graph_repo is None:
        return _empty_status(repo, "not_indexed")

    latest_run = await _latest_run(db, graph_repo)
    if latest_run is None:
        return _empty_status(repo, "not_indexed", graph_repo=graph_repo)

    sync_state = await _load_sync_state(db, repo=repo)
    run_history = await _load_run_history(db, graph_repo=graph_repo, limit=run_limit)
    summary = await _load_graph_summary(db, run=latest_run)
    stale_files = await _load_stale_files(
        db,
        graph_repo=graph_repo,
        sync_state=sync_state,
        limit=stale_limit,
    )
    parse_errors = await _load_parse_errors(db, run=latest_run, limit=error_limit)
    status = _derive_admin_status(
        graph_repo=graph_repo,
        latest_run=latest_run,
        sync_state=sync_state,
        stale_count=len(stale_files),
    )
    return _status_payload(
        repo,
        graph_repo=graph_repo,
        latest_run=latest_run,
        status=status,
        run_history=run_history,
        summary=summary,
        sync_state=sync_state,
        stale_files=stale_files,
        parse_errors=parse_errors,
    )


def _status_payload(
    repo: CodeRepository,
    *,
    graph_repo: CodeGraphRepository,
    latest_run: CodeGraphRun,
    status: str,
    run_history: list[CodeGraphRun],
    summary: dict[str, Any],
    sync_state: dict[str, Any],
    stale_files: list[dict[str, Any]],
    parse_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": status,
        "repository_id": repo.id,
        "project_id": repo.project_id,
        "graph_repository_id": graph_repo.id,
        "backend": graph_repo.graph_backend,
        "schema_version": graph_repo.graph_schema_version,
        "indexing_mode": graph_repo.indexing_mode,
        "staleness_state": graph_repo.staleness_state,
        "capabilities": _coerce_dict(repo.capabilities_json).get("graph") or {},
        "mirror": mirror_status(repo),  # path, bytes on disk, head, last fetch
        "latest_run": _serialize_graph_run(latest_run),
        "run_history": [_serialize_graph_run(run) for run in run_history],
        "summary": summary,
        "sync": sync_state,
        "stale_files": stale_files,
        "parse_errors": parse_errors,
        "metrics": {
            "latest_duration_ms": latest_run.duration_ms,
            "latest_file_count": latest_run.file_count,
            "latest_node_count": latest_run.node_count,
            "latest_edge_count": latest_run.edge_count,
            "latest_unresolved_reference_count": latest_run.unresolved_reference_count,
            "stale_file_count": len(stale_files),
            "parse_error_count": len(parse_errors),
        },
    }


async def _load_repository(db: AsyncSession, *, repository_id: str, project_id: str | None) -> CodeRepository:
    repo = await db.get(CodeRepository, str(repository_id or "").strip())
    if repo is None:
        raise HTTPException(status_code=404, detail="Code repository not found")
    if project_id and repo.project_id and repo.project_id != project_id:
        raise HTTPException(status_code=403, detail="Repository is not readable from the current project")
    require_repository_operation(repo, "read")
    return repo


__all__ = [
    "get_code_graph_admin_status",
    "get_code_graph_admin_status_for_repository",
]
