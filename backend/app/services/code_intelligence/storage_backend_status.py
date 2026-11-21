"""Per-backend readiness status for code intelligence repositories."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.code_intelligence.storage_runtime import _coerce_dict, _coerce_list

# (available, artifact_status, detail, mode) as reported for one backend layer.
BackendState = tuple[bool, str | None, str, str]

_ARTIFACT_BACKENDS = {"zoekt", "scip", "tree-sitter", "code_graph"}
_LAYER_KINDS = {"index", "semantic", "structure", "graph"}


def _resolve_graph_artifact_status(
    *, artifact: dict[str, Any], capabilities: dict[str, Any], backend: str
) -> tuple[bool, str | None, int, int, str]:
    available = False
    status = None
    node_count = 0
    edge_count = 0
    mode = "native"
    if backend == "code_graph":
        graph_caps = _coerce_dict(_coerce_dict(capabilities.get("graph")).get("code_graph"))
        available = bool(graph_caps.get("available"))
        status = str(_coerce_dict(artifact.get("code_graph")).get("status") or "").strip().lower() or str(
            _coerce_dict(artifact.get("graphify")).get("status") or ""
        ).strip().lower() or None
        node_count = int(_coerce_dict(artifact.get("code_graph") or artifact.get("graphify")).get("node_count") or 0)
        edge_count = int(_coerce_dict(artifact.get("code_graph") or artifact.get("graphify")).get("edge_count") or 0)
    return available, status, node_count, edge_count, mode


def _serialize_backend_status(
    *,
    kind: str,
    configured: str,
    effective: str,
    capabilities: dict[str, Any],
    snapshot: dict[str, Any],
    last_index_status: str | None,
) -> dict[str, Any]:
    configured_value = str(configured or "").strip().lower() or "auto"
    effective_value = str(effective or "").strip().lower() or "unknown"
    snapshot_data = _coerce_dict(snapshot)
    artifacts = _coerce_dict(snapshot_data.get("artifacts"))
    resolver = _STATE_RESOLVERS.get(kind)
    if resolver is None:
        available, artifact_status, detail, mode = True, None, "", "native"
    else:
        available, artifact_status, detail, mode = resolver(effective_value, capabilities, artifacts)

    ready = bool(available)
    if kind in _LAYER_KINDS and effective_value in _ARTIFACT_BACKENDS:
        ready = available and artifact_status == "ready"
    elif effective_value == "disabled":
        ready = True
    if str(last_index_status or "").strip().lower() == "error" and kind in _LAYER_KINDS:
        ready = False
    return {
        "configured": configured_value,
        "effective": effective_value,
        "available": bool(available),
        "ready": bool(ready),
        "artifact_status": artifact_status,
        "mode": mode,
        "detail": detail,
    }


def _index_state(effective_value: str, capabilities: dict[str, Any], artifacts: dict[str, Any]) -> BackendState:
    available = True
    artifact_status: str | None = None
    detail = ""
    mode = "native"
    if effective_value == "zoekt":
        zoekt_caps = _coerce_dict(_coerce_dict(capabilities.get("search")).get("zoekt"))
        binaries = _coerce_dict(zoekt_caps.get("binaries"))
        available = bool(zoekt_caps.get("available")) and bool(binaries.get("zoekt"))
        artifact_status = str(_coerce_dict(artifacts.get("zoekt")).get("status") or "").strip().lower() or None
        if artifact_status == "ready" and available:
            detail = "Zoekt index ready"
            mode = "indexed"
        elif artifact_status:
            detail = f"Zoekt artifact {artifact_status}"
            mode = "fallback" if not available else "degraded"
        elif not available:
            detail = "Zoekt search binary missing"
            mode = "fallback"
        else:
            detail = "Zoekt selected but no ready artifact"
            mode = "degraded"
    elif effective_value == "ripgrep":
        available = bool(_coerce_dict(_coerce_dict(capabilities.get("search")).get("ripgrep")).get("available"))
        detail = "ripgrep text search"
        mode = "fallback"
    return available, artifact_status, detail, mode


def _semantic_state(effective_value: str, capabilities: dict[str, Any], artifacts: dict[str, Any]) -> BackendState:
    available = True
    artifact_status: str | None = None
    detail = ""
    mode = "native"
    if effective_value == "scip":
        scip_caps = _coerce_dict(_coerce_dict(capabilities.get("semantic")).get("scip"))
        languages = _coerce_list(_coerce_dict(artifacts.get("scip")).get("languages"))
        ready_languages = [
            str(item.get("language") or "").strip()
            for item in languages
            if isinstance(item, dict) and item.get("status") == "ready"
        ]
        available = any(bool(value) for value in _coerce_dict(scip_caps.get("languages")).values())
        artifact_status = str(_coerce_dict(artifacts.get("scip")).get("status") or "").strip().lower() or None
        if ready_languages:
            detail = f"SCIP ready: {', '.join(sorted(ready_languages)[:4])}"
            mode = "indexed"
        elif artifact_status and artifact_status != "ready":
            detail = f"SCIP artifact {artifact_status}"
            mode = "fallback"
        elif not available:
            detail = "SCIP indexers not installed"
            mode = "fallback"
        else:
            detail = "SCIP selected but no ready language artifacts"
            mode = "degraded"
    elif effective_value == "regex":
        available = True
        detail = "Regex symbol heuristics"
        mode = "fallback"
    elif effective_value == "lsp":
        available = True
        detail = "LSP semantic lookup"
    return available, artifact_status, detail, mode


def _structure_state(effective_value: str, capabilities: dict[str, Any], artifacts: dict[str, Any]) -> BackendState:
    available = True
    artifact_status: str | None = None
    detail = ""
    mode = "native"
    if effective_value == "tree-sitter":
        tree_caps = _coerce_dict(_coerce_dict(capabilities.get("structure")).get("tree_sitter"))
        available = bool(tree_caps.get("available"))
        artifact = _coerce_dict(artifacts.get("tree_sitter"))
        artifact_status = str(artifact.get("status") or "").strip().lower() or None
        file_count = int(artifact.get("file_count") or 0)
        if artifact_status == "ready":
            detail = f"Tree-sitter structure index ready · {file_count} files"
            mode = "indexed"
        else:
            detail = "Tree-sitter structural parsing" if available else "Tree-sitter unavailable"
            mode = "native" if available else "fallback"
    elif effective_value == "regex":
        available = True
        detail = "Regex structure fallback"
        mode = "fallback"
    return available, artifact_status, detail, mode


def _graph_state(effective_value: str, capabilities: dict[str, Any], artifacts: dict[str, Any]) -> BackendState:
    available = True
    artifact_status: str | None = None
    detail = ""
    mode = "native"
    if effective_value in {"code_graph", "graphify"}:
        effective_backend = "code_graph"
        available, artifact_status, node_count, edge_count, mode = _resolve_graph_artifact_status(
            artifact=artifacts, capabilities=capabilities, backend=effective_backend
        )
        artifact = _coerce_dict(artifacts.get("code_graph") or artifacts.get("graphify"))
        backend = str(artifact.get("backend") or effective_backend).strip() or effective_backend
        if artifact_status == "ready":
            detail = f"Code graph ready via {backend} · {node_count} nodes · {edge_count} edges"
            mode = "indexed"
        elif artifact_status:
            detail = f"Code graph artifact {artifact_status}"
            mode = "fallback"
        else:
            detail = "Code graph context"
            mode = "native" if available else "fallback"
    elif effective_value == "disabled":
        available = True
        detail = "Graph layer disabled"
        mode = "disabled"
    return available, artifact_status, detail, mode


_STATE_RESOLVERS: dict[str, Callable[[str, dict[str, Any], dict[str, Any]], BackendState]] = {
    "index": _index_state,
    "semantic": _semantic_state,
    "structure": _structure_state,
    "graph": _graph_state,
}
