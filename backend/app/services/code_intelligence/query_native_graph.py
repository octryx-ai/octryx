"""Native code graph lookups and payload shaping behind the code intelligence queries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.models import CodeGraphEdge, CodeGraphNode
from app.services.code_intelligence.graph_analytics import get_code_graph_affected
from app.services.code_intelligence.graph_query_serializers import serialize_graph_context
from app.services.code_intelligence.graph_query_support import find_nodes, load_graph_context
from app.services.code_intelligence.storage_runtime import _coerce_dict, _truncate


def _graph_summary_payload(resolved: dict[str, Any]) -> dict[str, Any]:
    snapshot = resolved["snapshot"]
    artifact = _coerce_dict(_coerce_dict(snapshot.get("artifacts")).get("code_graph"))
    if not artifact:
        artifact = _coerce_dict(_coerce_dict(snapshot.get("artifacts")).get("graphify"))
    graph_path = str(artifact.get("graph_path") or "").strip()
    report_path = str(artifact.get("report_path") or "").strip()
    try:
        graph_payload = json.loads(Path(graph_path).read_text(encoding="utf-8")) if graph_path else {}
    except Exception:
        graph_payload = {}
    try:
        report = Path(report_path).read_text(encoding="utf-8", errors="replace") if report_path else ""
    except Exception:
        report = ""
    artifact_backend = str(artifact.get("backend") or "internal")
    return {
        "repository": resolved["repository"],
        "graph_backend": str(snapshot.get("engines", {}).get("graph_backend") or artifact.get("backend") or "").strip()
        or "disabled",
        "graph_status": str(artifact.get("status") or "missing"),
        "backend": "internal" if artifact_backend == "code_graph" else artifact_backend,
        "node_count": int(artifact.get("node_count") or graph_payload.get("node_count") or 0),
        "edge_count": int(artifact.get("edge_count") or graph_payload.get("edge_count") or 0),
        "import_edge_count": int(artifact.get("import_edge_count") or 0),
        "graph_path": graph_path or None,
        "report_path": report_path or None,
        "report_excerpt": _truncate(report or str(artifact.get("report_excerpt") or ""), max_chars=2000),
        "engines": snapshot.get("engines", {}),
    }


async def _native_graph_matches(
    *,
    db,
    repository_id: str | None,
    project_id: str | None,
    query: str,
    limit: int,
    symbol_only: bool = False,
) -> tuple[Any | None, list[CodeGraphNode]]:
    try:
        ctx = await load_graph_context(db=db, repository_id=repository_id, project_id=project_id)
    except Exception:
        return None, []
    if ctx is None:
        return None, []
    nodes = await find_nodes(db, ctx=ctx, query=query, name=query, limit=limit)
    if symbol_only:
        nodes = [node for node in nodes if node.node_type != "file"]
    return ctx, nodes[:limit]


async def _native_graph_references(
    *,
    db,
    repository_id: str | None,
    project_id: str | None,
    symbol: str,
    relations: set[str],
    limit: int,
) -> tuple[Any | None, list[CodeGraphNode]]:
    ctx, targets = await _native_graph_matches(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
        query=symbol,
        limit=10,
        symbol_only=True,
    )
    if ctx is None or not targets:
        return ctx, []
    target_ids = {node.id for node in targets}
    rows = (
        await db.execute(
            select(CodeGraphNode)
            .join(CodeGraphEdge, CodeGraphEdge.source_node_id == CodeGraphNode.id)
            .where(
                CodeGraphEdge.run_id == ctx.run.id,
                CodeGraphEdge.target_node_id.in_(target_ids),
                CodeGraphEdge.relation.in_(relations),
                CodeGraphEdge.is_current.is_(True),
                CodeGraphNode.is_current.is_(True),
            )
            .limit(max(1, min(int(limit or 50), 200)))
        )
    ).scalars().all()
    return ctx, list(rows)


async def _native_graph_impact(
    *,
    db,
    repository_id: str | None,
    project_id: str | None,
    symbol: str,
    limit: int,
) -> dict[str, Any]:
    if not repository_id:
        return {}
    try:
        impact = await get_code_graph_affected(
            db=db,
            repository_id=repository_id,
            project_id=project_id,
            query=symbol,
            depth=2,
            max_nodes=max(1, min(int(limit or 50), 50)),
        )
    except Exception:
        return {}
    if impact.get("status") not in {"ready", "truncated"}:
        return {}
    return {
        "status": impact.get("status"),
        "graph": impact.get("graph", {}),
        "affected_files": impact.get("affected_files", []),
        "affected_nodes": impact.get("affected_nodes", []),
        "edges": impact.get("edges", []),
        "semantics": impact.get("semantics", ""),
    }


def _legacy_nodes(nodes: list[CodeGraphNode]) -> list[dict[str, Any]]:
    return [
        {
            "path": node.path or "",
            "line": int(node.line_start or 1),
            "end_line": int(node.line_end or node.line_start or 1),
            "name": node.name,
            "kind": node.node_type,
            "language": node.language,
            "signature": node.signature or node.name,
            "backend": "native_graph",
            "confidence": node.confidence,
            "graph_node_id": node.id,
            "graph_external_id": node.external_id,
            "is_stale": bool(node.is_stale),
        }
        for node in nodes
    ]


def _serialize_native_graph_resolution(ctx: Any | None, nodes: list[CodeGraphNode]) -> dict[str, Any]:
    return {
        "available": ctx is not None,
        "used": bool(nodes),
        "match_count": len(nodes),
        "graph": serialize_graph_context(ctx) if ctx is not None else {},
    }


def _reference_backend_label(*, native_graph_used: bool, lsp_used: bool, fallback_backend: str) -> str:
    if native_graph_used and lsp_used:
        return "native_graph+lsp+text"
    if native_graph_used:
        return "native_graph+text"
    if lsp_used:
        return "lsp+text"
    return fallback_backend
