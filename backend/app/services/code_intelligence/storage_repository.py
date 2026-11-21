"""Repository/backend serialization helpers for code intelligence storage."""

from __future__ import annotations

from typing import Any

from app.services.code_intelligence.storage_runtime import (
    _coerce_dict,
    _latest_snapshot_path,
    _read_snapshot,
)

from ...models import CodeIndexRun, CodeRepository
from .storage_backend_status import _serialize_backend_status


def _resolve_repository_backends(
    repo: CodeRepository, *, capabilities: dict[str, Any], latest_summary: dict[str, Any]
) -> dict[str, str]:
    engines = _coerce_dict(latest_summary.get("engines"))
    index_backend = str(engines.get("index_backend") or repo.index_backend or "").strip().lower()
    if index_backend in {"", "auto"}:
        index_backend = (
            "zoekt"
            if _coerce_dict(_coerce_dict(capabilities.get("search")).get("zoekt")).get("available")
            else "ripgrep"
        )
    semantic_backend = str(engines.get("semantic_backend") or repo.semantic_backend or "").strip().lower()
    if semantic_backend in {"", "auto"}:
        scip_languages = _coerce_dict(
            _coerce_dict(_coerce_dict(capabilities.get("semantic")).get("scip")).get("languages")
        )
        semantic_backend = "scip" if any(bool(value) for value in scip_languages.values()) else "regex"
    structure_backend = str(engines.get("structure_backend") or repo.structure_backend or "").strip().lower()
    if structure_backend in {"", "auto"}:
        structure_backend = (
            "tree-sitter"
            if _coerce_dict(_coerce_dict(capabilities.get("structure")).get("tree_sitter")).get("available")
            else "regex"
        )
    graph_backend = str(engines.get("graph_backend") or repo.graph_backend or "").strip().lower()
    if graph_backend in {"", "auto"}:
        graph_backend = (
            "code_graph"
            if _coerce_dict(_coerce_dict(capabilities.get("graph")).get("code_graph")).get("available")
            else "disabled"
        )
    if graph_backend == "graphify":
        graph_backend = "code_graph"
    if graph_backend not in {"code_graph", "disabled"}:
        graph_backend = "disabled"
    return {
        "index": index_backend,
        "semantic": semantic_backend,
        "structure": structure_backend,
        "graph": graph_backend,
    }

def _serialize_repository(repo: CodeRepository) -> dict[str, Any]:
    latest_summary = _coerce_dict(repo.latest_index_summary)
    capabilities = _coerce_dict(repo.capabilities_json)
    latest_snapshot = (
        _coerce_dict(_read_snapshot(_latest_snapshot_path(repo.id))) if repo.last_index_status == "ready" else {}
    )
    resolved_backends = _resolve_repository_backends(repo, capabilities=capabilities, latest_summary=latest_summary)
    backend_status = {
        kind: _serialize_backend_status(
            kind=kind,
            configured=configured,
            effective=resolved_backends[kind],
            capabilities=capabilities,
            snapshot=latest_snapshot,
            last_index_status=repo.last_index_status,
        )
        for kind, configured in (
            ("index", repo.index_backend),
            ("semantic", repo.semantic_backend),
            ("structure", repo.structure_backend),
            ("graph", repo.graph_backend),
        )
    }
    index_runs = repo.__dict__.get("index_runs") or []
    return {
        "id": repo.id,
        "project_id": repo.project_id,
        "name": repo.name,
        "description": repo.description or "",
        "repo_root": repo.repo_root,
        "provider": repo.provider,
        "remote_url": repo.remote_url,
        "default_branch": repo.default_branch,
        "index_backend": repo.index_backend,
        "semantic_backend": repo.semantic_backend,
        "structure_backend": repo.structure_backend,
        "graph_backend": repo.graph_backend,
        "config_json": _coerce_dict(repo.config_json),
        "capabilities_json": capabilities,
        "effective_backends": resolved_backends,
        "backend_status": backend_status,
        "latest_index_summary": latest_summary,
        "last_index_status": repo.last_index_status,
        "last_indexed_at": repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
        "last_index_error": repo.last_index_error,
        "is_active": bool(repo.is_active),
        "index_runs": [_serialize_index_run(run) for run in index_runs[:10]],
        "created_at": repo.created_at.isoformat() if repo.created_at else None,
        "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
    }


def _serialize_index_run(run: CodeIndexRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "repository_id": run.repository_id,
        "status": run.status,
        "trigger": run.trigger,
        "index_backend": run.index_backend,
        "semantic_backend": run.semantic_backend,
        "structure_backend": run.structure_backend,
        "graph_backend": run.graph_backend,
        "files_indexed": int(run.files_indexed or 0),
        "symbols_indexed": int(run.symbols_indexed or 0),
        "references_indexed": int(run.references_indexed or 0),
        "duration_ms": int(run.duration_ms) if run.duration_ms is not None else None,
        "storage_path": run.storage_path,
        "languages_json": _coerce_dict(run.languages_json),
        "summary_json": _coerce_dict(run.summary_json),
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
