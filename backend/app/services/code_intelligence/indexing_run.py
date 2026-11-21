"""Steps of one code index run: backend choice, cache check, snapshot, artifacts and run bookkeeping."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CodeIndexRun
from ...time_utils import utc_now
from ..error_facts import error_facts, error_text
from .graph import _maybe_build_graphify_artifacts
from .graph_persist import _persist_code_graph_artifacts
from .graph_sync import build_code_graph_sync_plan, update_graph_repository_staleness_from_plan
from .indexing_snapshot import _build_snapshot
from .outline import _outline_from_symbols, _python_ast_outline, _tree_sitter_outline
from .outline_java import _tree_sitter_java_outline
from .process import _maybe_build_zoekt_index
from .semantic_build import _maybe_build_scip_indices
from .storage_repository import _serialize_repository
from .storage_runtime import _coerce_dict, _read_snapshot
from .structure import _maybe_build_structure_index


def _files_indexed_count(*, snapshot: dict[str, Any], sync_plan: dict[str, Any]) -> int:
    if sync_plan.get("indexing_mode") == "incremental":
        return int(sync_plan.get("files_to_index") or 0)
    return int(snapshot.get("file_count") or 0)


async def _checked_repo_root(db: AsyncSession, repo: Any, repo_root: Path) -> None:
    if not repo_root.exists() or not repo_root.is_dir():
        repo.last_index_status = "error"
        repo.last_index_error = f"Repository root does not exist: {repo_root}"
        await db.commit()
        raise HTTPException(status_code=400, detail=repo.last_index_error)


def _resolve_backends(repo: Any, capabilities: dict[str, Any]) -> dict[str, str]:
    """The four engine backends; an explicit repository setting wins over ``auto``."""
    return {
        "index_backend": (
            repo.index_backend
            if repo.index_backend not in {"", "auto"}
            else ("zoekt" if capabilities["search"]["zoekt"]["available"] else "ripgrep")
        ),
        "semantic_backend": (
            repo.semantic_backend
            if repo.semantic_backend not in {"", "auto"}
            else ("scip" if any(capabilities["semantic"]["scip"]["languages"].values()) else "regex")
        ),
        "structure_backend": (
            repo.structure_backend
            if repo.structure_backend not in {"", "auto"}
            else ("tree-sitter" if capabilities["structure"]["tree_sitter"]["available"] else "regex")
        ),
        "graph_backend": (
            repo.graph_backend
            if repo.graph_backend not in {"", "auto"}
            else ("code_graph" if capabilities["graph"]["code_graph"]["available"] else "disabled")
        ),
    }


async def _graph_sync_plan(
    db: AsyncSession, *, repo: Any, repo_root: Path, force: bool, graph_sync_enabled: bool
) -> dict[str, Any]:
    if not graph_sync_enabled:
        return {}
    return await build_code_graph_sync_plan(
        db=db,
        repository_id=repo.id,
        repo_root=repo_root,
        force=force,
    )


async def _cached_index_result(
    db: AsyncSession,
    *,
    repo: Any,
    force: bool,
    latest_path: Path,
    graph_sync_enabled: bool,
    sync_plan: dict[str, Any],
) -> dict[str, Any] | None:
    """The cached snapshot result, or ``None`` when the repository must be indexed again."""
    if not force and latest_path.exists() and repo.last_index_status == "ready":
        snapshot = _read_snapshot(latest_path)
        if snapshot:
            if graph_sync_enabled and sync_plan.get("has_changes"):
                await update_graph_repository_staleness_from_plan(
                    db=db,
                    repository_id=repo.id,
                    plan=sync_plan,
                )
                await db.commit()
            elif graph_sync_enabled:
                snapshot.setdefault("artifacts", {}).setdefault("code_graph", {})["sync"] = sync_plan
                return {"status": "cached", "repository": _serialize_repository(repo), "snapshot": snapshot}
            else:
                return {"status": "cached", "repository": _serialize_repository(repo), "snapshot": snapshot}
        if snapshot and not graph_sync_enabled:
            return {"status": "cached", "repository": _serialize_repository(repo), "snapshot": snapshot}
    return None


async def _start_index_run(
    db: AsyncSession, *, repo: Any, trigger: str, backends: dict[str, str], capabilities: dict[str, Any]
) -> CodeIndexRun:
    run = CodeIndexRun(
        id=str(uuid.uuid4()),
        repository_id=repo.id,
        status="running",
        trigger=trigger,
        index_backend=backends["index_backend"],
        semantic_backend=backends["semantic_backend"],
        structure_backend=backends["structure_backend"],
        graph_backend=backends["graph_backend"],
        started_at=utc_now(),
    )
    db.add(run)
    repo.last_index_status = "running"
    repo.last_index_error = None
    repo.capabilities_json = capabilities
    await db.commit()
    return run


async def _build_indexed_snapshot(
    db: AsyncSession,
    *,
    repo: Any,
    repo_root: Path,
    run: CodeIndexRun,
    capabilities: dict[str, Any],
    backends: dict[str, str],
    sync_plan: dict[str, Any],
) -> dict[str, Any]:
    """Build the snapshot and its engine artifacts.

    ``backends`` is updated in place when a ``graphify`` request is served by the native graph,
    so the caller logs the backend that really ran even when a later step fails.
    """
    snapshot = await asyncio.to_thread(_build_snapshot, repo_root, capabilities=capabilities, **backends)
    if backends["semantic_backend"] == "scip":
        snapshot.setdefault("artifacts", {})["scip"] = await _maybe_build_scip_indices(
            repository_id=repo.id,
            repo_root=repo_root,
            snapshot=snapshot,
        )
    if backends["index_backend"] == "zoekt":
        snapshot.setdefault("artifacts", {})["zoekt"] = await _maybe_build_zoekt_index(
            repository_id=repo.id,
            repo_root=repo_root,
        )
    if backends["structure_backend"] == "tree-sitter":
        snapshot.setdefault("artifacts", {})["tree_sitter"] = await _maybe_build_structure_index(
            repository_id=repo.id,
            repo_root=repo_root,
            snapshot=snapshot,
            python_outline_builder=_python_ast_outline,
            java_outline_builder=_tree_sitter_java_outline,
            symbol_outline_builder=_outline_from_symbols,
            tree_outline_builder=_tree_sitter_outline,
        )
    if backends["graph_backend"] in {"code_graph", "graphify"}:
        await _build_graph_artifact(
            db, repo=repo, repo_root=repo_root, run=run, snapshot=snapshot, backends=backends, sync_plan=sync_plan
        )
    return snapshot


async def _build_graph_artifact(
    db: AsyncSession,
    *,
    repo: Any,
    repo_root: Path,
    run: CodeIndexRun,
    snapshot: dict[str, Any],
    backends: dict[str, str],
    sync_plan: dict[str, Any],
) -> None:
    requested_graph_backend = backends["graph_backend"]
    graph_artifact = await _maybe_build_graphify_artifacts(
        repository_id=repo.id,
        repo_root=repo_root,
        snapshot=snapshot,
    )
    snapshot.setdefault("artifacts", {})["code_graph"] = graph_artifact
    snapshot["artifacts"]["code_graph"]["sync"] = sync_plan
    if requested_graph_backend == "graphify":
        snapshot["artifacts"]["graphify"] = graph_artifact
    if backends["graph_backend"] == "graphify":
        backends["graph_backend"] = "code_graph"
        snapshot["engines"]["graph_backend"] = "code_graph"
    run.graph_backend = backends["graph_backend"]
    try:
        graph_persistence = await _persist_code_graph_artifacts(
            db=db,
            repository_id=repo.id,
            repo_root=repo_root,
            snapshot=snapshot,
            artifact=graph_artifact,
            graph_trigger=run.trigger,
            sync_plan=sync_plan,
        )
        snapshot["artifacts"]["code_graph"]["persistence"] = {"status": "ready", **graph_persistence}
    except SQLAlchemyError as exc:
        snapshot["artifacts"]["code_graph"]["persistence"] = {
            "status": "failed",
            **error_facts("code_graph_persistence_failed", exc),
        }


def _record_index_success(
    run: CodeIndexRun,
    *,
    repo: Any,
    snapshot: dict[str, Any],
    sync_plan: dict[str, Any],
    latest_path: Path,
    start: float,
    backends: dict[str, str],
) -> None:
    run.status = "ready"
    run.duration_ms = int((time.perf_counter() - start) * 1000)
    run.files_indexed = _files_indexed_count(snapshot=snapshot, sync_plan=sync_plan)
    run.symbols_indexed = int(snapshot["symbol_count"])
    run.references_indexed = max(0, snapshot["symbol_count"] - len({item["name"] for item in snapshot["symbols"]}))
    run.languages_json = _coerce_dict(snapshot.get("languages"))
    run.summary_json = {
        "file_count": snapshot["file_count"],
        "symbol_count": snapshot["symbol_count"],
        "languages": snapshot["languages"],
        "engines": snapshot["engines"],
        "sync": sync_plan,
    }
    run.storage_path = str(latest_path)
    run.finished_at = utc_now()
    repo.latest_index_summary = run.summary_json
    repo.last_index_status = "ready"
    repo.last_indexed_at = utc_now()
    repo.last_index_error = None
    repo.index_backend = backends["index_backend"]
    repo.semantic_backend = backends["semantic_backend"]
    repo.structure_backend = backends["structure_backend"]
    repo.graph_backend = backends["graph_backend"]


async def _record_index_failure(
    db: AsyncSession, run: CodeIndexRun, *, repo: Any, exc: Exception, start: float
) -> None:
    run.status = "error"
    run.error = error_text("code_index_failed", exc)
    run.duration_ms = int((time.perf_counter() - start) * 1000)
    run.finished_at = utc_now()
    repo.last_index_status = "error"
    repo.last_index_error = run.error
    await db.commit()
