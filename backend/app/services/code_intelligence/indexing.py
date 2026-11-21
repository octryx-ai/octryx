"""Indexing and artifact-building helpers for code intelligence."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..project_resource_policy import require_repository_operation
from .indexing_run import (
    _build_indexed_snapshot,
    _cached_index_result,
    _checked_repo_root,
    _graph_sync_plan,
    _record_index_failure,
    _record_index_success,
    _resolve_backends,
    _start_index_run,
)
from .indexing_snapshot import _build_snapshot
from .repository import get_code_repository
from .storage_capabilities import detect_code_intelligence_capabilities
from .storage_repository import _serialize_index_run, _serialize_repository
from .storage_runtime import (
    _latest_snapshot_path,
    _normalize_path,
    _read_snapshot,
    _write_snapshot,
)

logger = logging.getLogger(__name__)


async def run_code_index(
    db: AsyncSession,
    *,
    repository_id: str,
    force: bool = False,
    trigger: str = "manual",
) -> dict[str, Any]:
    repo = await get_code_repository(db, repository_id)
    require_repository_operation(repo, "index")
    logger.info(
        "code_graph.index.requested",
        extra={"repository_id": repo.id, "project_id": repo.project_id, "trigger": trigger, "force": bool(force)},
    )
    repo_root = _normalize_path(repo.repo_root)
    await _checked_repo_root(db, repo, repo_root)

    capabilities = detect_code_intelligence_capabilities()
    backends = _resolve_backends(repo, capabilities)
    latest_path = _latest_snapshot_path(repo.id)
    graph_sync_enabled = backends["graph_backend"] in {"code_graph", "graphify"}
    sync_plan = await _graph_sync_plan(
        db, repo=repo, repo_root=repo_root, force=force, graph_sync_enabled=graph_sync_enabled
    )
    cached = await _cached_index_result(
        db, repo=repo, force=force, latest_path=latest_path, graph_sync_enabled=graph_sync_enabled, sync_plan=sync_plan
    )
    if cached is not None:
        return cached

    run = await _start_index_run(db, repo=repo, trigger=trigger, backends=backends, capabilities=capabilities)
    start = time.perf_counter()
    try:
        snapshot = await _build_indexed_snapshot(
            db, repo=repo, repo_root=repo_root, run=run,
            capabilities=capabilities, backends=backends, sync_plan=sync_plan,
        )
        _write_snapshot(latest_path, snapshot)
        _record_index_success(
            run,
            repo=repo,
            snapshot=snapshot,
            sync_plan=sync_plan,
            latest_path=latest_path,
            start=start,
            backends=backends,
        )
        await db.commit()
        await db.refresh(repo)
        _log_index_completed(repo, run=run, trigger=trigger, graph_backend=backends["graph_backend"])
        return {
            "status": "indexed",
            "repository": _serialize_repository(repo),
            "run": _serialize_index_run(run),
            "snapshot": snapshot,
        }
    except Exception as exc:
        await _record_index_failure(db, run, repo=repo, exc=exc, start=start)
        _log_index_failed(repo, run=run, trigger=trigger, graph_backend=backends["graph_backend"])
        raise


def _log_index_completed(repo: Any, *, run: Any, trigger: str, graph_backend: str) -> None:
    logger.info(
        "code_graph.index.completed",
        extra={
            "repository_id": repo.id,
            "project_id": repo.project_id,
            "trigger": trigger,
            "status": run.status,
            "duration_ms": run.duration_ms,
            "files_indexed": run.files_indexed,
            "symbols_indexed": run.symbols_indexed,
            "graph_backend": graph_backend,
        },
    )


def _log_index_failed(repo: Any, *, run: Any, trigger: str, graph_backend: str) -> None:
    # Called from the except block, so logger.exception still carries the active traceback.
    logger.exception(
        "code_graph.index.failed",
        extra={
            "repository_id": repo.id,
            "project_id": repo.project_id,
            "trigger": trigger,
            "duration_ms": run.duration_ms,
            "graph_backend": graph_backend,
        },
    )


async def get_repository_snapshot(
    *,
    db: AsyncSession | None,
    repository_id: str | None,
    cwd: Path | None = None,
    project_id: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if repository_id and db is not None:
        repo = await get_code_repository(db, repository_id)
        require_repository_operation(repo, "read")
        latest_path = _latest_snapshot_path(repo.id)
        snapshot = _read_snapshot(latest_path)
        if snapshot and not force_refresh:
            return {"repository": _serialize_repository(repo), "snapshot": snapshot}
        indexed = await run_code_index(db, repository_id=repo.id, force=force_refresh, trigger="tool")
        return {"repository": indexed["repository"], "snapshot": indexed["snapshot"]}

    repo_root = _normalize_path(cwd or ".")
    capabilities = detect_code_intelligence_capabilities()
    snapshot = await asyncio.to_thread(
        _build_snapshot,
        repo_root,
        capabilities=capabilities,
        index_backend="ripgrep",
        semantic_backend="regex",
        structure_backend="tree-sitter" if capabilities["structure"]["tree_sitter"]["available"] else "regex",
        graph_backend="code_graph" if capabilities["graph"]["code_graph"]["available"] else "disabled",
    )
    return {
        "repository": {
            "id": None,
            "project_id": project_id,
            "name": repo_root.name,
            "repo_root": str(repo_root),
            "index_backend": snapshot["engines"]["index_backend"],
            "semantic_backend": snapshot["engines"]["semantic_backend"],
            "structure_backend": snapshot["engines"]["structure_backend"],
            "graph_backend": snapshot["engines"]["graph_backend"],
            "capabilities_json": capabilities,
        },
        "snapshot": snapshot,
    }


__all__ = [
    "get_repository_snapshot",
    "run_code_index",
]
