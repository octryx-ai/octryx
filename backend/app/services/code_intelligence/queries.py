"""Query helpers for code intelligence."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.code_intelligence.query_native_graph import (
    _graph_summary_payload,
    _legacy_nodes,
    _native_graph_impact,
    _native_graph_matches,
    _native_graph_references,
    _reference_backend_label,
    _serialize_native_graph_resolution,
)
from app.services.code_intelligence.symbol_analysis import (
    _lsp_references_for_definition,
    _lsp_workspace_symbol_matches,
    _rank_symbol,
    _scip_definitions,
    _scip_references,
)

from .storage_runtime import _coerce_list
from .storage_search import _search_repository_text


def _get_snapshot(*, db, repository_id: str | None, cwd: Path, project_id: str | None):
    from .indexing import get_repository_snapshot

    return get_repository_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)


async def search_repository_code(
    *, db, repository_id: str | None, cwd: Path, project_id: str | None, query: str, limit: int = 20
) -> dict[str, Any]:
    resolved = await _get_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)
    snapshot = resolved["snapshot"]
    repo_root = Path(snapshot["repo_root"]).resolve()
    graph_context, graph_matches = await _native_graph_matches(
        db=db,
        repository_id=repository_id or resolved["repository"].get("id"),
        project_id=project_id,
        query=query,
        limit=limit,
    )
    text_matches = await _search_repository_text(snapshot, repo_root=repo_root, query=query, limit=limit)
    symbol_matches = sorted(
        [
            symbol
            for symbol in _coerce_list(snapshot.get("symbols"))
            if query.lower() in str(symbol.get("name") or "").lower()
        ],
        key=lambda item: _rank_symbol(item, query),
    )[:limit]
    return {
        "repository": resolved["repository"],
        "query": query,
        "resolution_backend": "native_graph+text" if graph_matches else "snapshot_text",
        "native_graph": _serialize_native_graph_resolution(graph_context, graph_matches),
        "search_backend": text_matches["backend"],
        "text_matches": text_matches["results"],
        "symbol_matches": symbol_matches,
        "total_text_matches": len(text_matches["results"]),
        "total_symbol_matches": len(symbol_matches),
        "engines": snapshot.get("engines", {}),
    }


async def find_symbol_definition(
    *, db, repository_id: str | None, cwd: Path, project_id: str | None, symbol: str
) -> dict[str, Any]:
    resolved = await _get_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)
    snapshot = resolved["snapshot"]
    graph_context, graph_matches = await _native_graph_matches(
        db=db,
        repository_id=repository_id or resolved["repository"].get("id"),
        project_id=project_id,
        query=symbol,
        limit=25,
        symbol_only=True,
    )
    symbols = (
        _scip_definitions(snapshot, symbol=symbol)
        if snapshot.get("engines", {}).get("semantic_backend") == "scip"
        else []
    )
    if not symbols:
        symbols = [
            item
            for item in _coerce_list(snapshot.get("symbols"))
            if str(item.get("name") or "").lower() == symbol.lower()
        ]
    if not symbols:
        symbols = [
            item
            for item in _coerce_list(snapshot.get("symbols"))
            if symbol.lower() in str(item.get("name") or "").lower()
        ]
    symbols = sorted(symbols, key=lambda item: _rank_symbol(item, symbol))
    lsp_symbols = (
        await _lsp_workspace_symbol_matches(repo_root=Path(snapshot["repo_root"]).resolve(), symbol=symbol)
        if (not symbols or snapshot.get("engines", {}).get("semantic_backend") != "scip")
        else []
    )
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for item in [*symbols, *lsp_symbols]:
        key = (str(item.get("path") or ""), int(item.get("line") or 1), str(item.get("name") or ""))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return {
        "repository": resolved["repository"],
        "symbol": symbol,
        "definitions": [*_legacy_nodes(graph_matches), *merged][:25],
        "resolution_backend": "native_graph+fallback" if graph_matches else "snapshot_fallback",
        "native_graph": _serialize_native_graph_resolution(graph_context, graph_matches),
        "engines": snapshot.get("engines", {}),
    }


async def find_symbol_references(
    *, db, repository_id: str | None, cwd: Path, project_id: str | None, symbol: str, limit: int = 50
) -> dict[str, Any]:
    resolved = await _get_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)
    snapshot = resolved["snapshot"]
    repo_root = Path(snapshot["repo_root"]).resolve()
    definitions = await find_symbol_definition(
        db=db, repository_id=repository_id, cwd=cwd, project_id=project_id, symbol=symbol
    )
    graph_context, graph_reference_nodes = await _native_graph_references(
        db=db,
        repository_id=repository_id or resolved["repository"].get("id"),
        project_id=project_id,
        symbol=symbol,
        relations={"calls", "references", "uses", "routes_to", "tested_by"},
        limit=limit,
    )
    definition_keys = {(item.get("path"), int(item.get("line") or 0)) for item in definitions.get("definitions", [])}
    scip_refs, text_matches = await _reference_text_matches(snapshot, repo_root=repo_root, symbol=symbol, limit=limit)
    references = [
        {**match, "is_definition": (match.get("path"), int(match.get("line") or 0)) in definition_keys}
        for match in text_matches["results"]
    ]
    lsp_references = (
        await _lsp_references_for_definition(
            repo_root=repo_root, definition=definitions["definitions"][0], include_declaration=True
        )
        if (definitions.get("definitions") and not scip_refs)
        else []
    )
    _merge_lsp_references(references, lsp_references, definition_keys=definition_keys)
    return {
        "repository": resolved["repository"],
        "symbol": symbol,
        "search_backend": _reference_backend_label(
            native_graph_used=bool(graph_reference_nodes),
            lsp_used=bool(lsp_references),
            fallback_backend=str(text_matches["backend"]),
        ),
        "references": [*_legacy_nodes(graph_reference_nodes), *references],
        "total_references": len(graph_reference_nodes) + len(references),
        "definitions": definitions.get("definitions", []),
        "resolution_backend": "native_graph+fallback" if graph_reference_nodes else "snapshot_fallback",
        "native_graph": _serialize_native_graph_resolution(graph_context, graph_reference_nodes),
    }


async def find_symbol_callers(
    *, db, repository_id: str | None, cwd: Path, project_id: str | None, symbol: str, limit: int = 50
) -> dict[str, Any]:
    resolved = await _get_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)
    snapshot = resolved["snapshot"]
    repo_root = Path(snapshot["repo_root"]).resolve()
    graph_context, graph_callers = await _native_graph_references(
        db=db,
        repository_id=repository_id or resolved["repository"].get("id"),
        project_id=project_id,
        symbol=symbol,
        relations={"calls"},
        limit=limit,
    )
    text_matches = await _search_repository_text(
        snapshot, repo_root=repo_root, query=rf"(?:\b|\.|->){re.escape(symbol)}\s*\(", limit=limit, case_sensitive=True
    )
    return {
        "repository": resolved["repository"],
        "symbol": symbol,
        "search_backend": "native_graph+text" if graph_callers else text_matches["backend"],
        "callers": [*_legacy_nodes(graph_callers), *text_matches["results"]],
        "total_callers": len(graph_callers) + len(text_matches["results"]),
        "resolution_backend": "native_graph+fallback" if graph_callers else "snapshot_fallback",
        "native_graph": _serialize_native_graph_resolution(graph_context, graph_callers),
    }


async def build_impact_analysis(
    *, db, repository_id: str | None, cwd: Path, project_id: str | None, symbol: str, limit: int = 50
) -> dict[str, Any]:
    graph_impact = await _native_graph_impact(
        db=db,
        repository_id=repository_id,
        project_id=project_id,
        symbol=symbol,
        limit=limit,
    )
    definitions = await find_symbol_definition(
        db=db, repository_id=repository_id, cwd=cwd, project_id=project_id, symbol=symbol
    )
    references = await find_symbol_references(
        db=db, repository_id=repository_id, cwd=cwd, project_id=project_id, symbol=symbol, limit=limit
    )
    callers = await find_symbol_callers(
        db=db, repository_id=repository_id, cwd=cwd, project_id=project_id, symbol=symbol, limit=limit
    )
    impacted_files: Counter[str] = Counter()
    for item in references.get("references", []):
        path = str(item.get("path") or "")
        if path:
            impacted_files[path] += 1
    related_paths = [path for path, _count in impacted_files.most_common(10)]
    related_symbols: list[dict[str, Any]] = []
    seen_paths = set(related_paths)
    for definition in definitions.get("definitions", []):
        seen_paths.add(str(definition.get("path") or ""))
    resolved = await _get_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)
    for item in _coerce_list(resolved["snapshot"].get("symbols")):
        path = str(item.get("path") or "")
        if path in seen_paths and str(item.get("name") or "").lower() != symbol.lower():
            related_symbols.append(item)
        if len(related_symbols) >= 25:
            break
    risk = (
        "high"
        if len(related_paths) >= 8 or len(callers.get("callers", [])) >= 15
        else "medium"
        if len(related_paths) >= 4 or len(callers.get("callers", [])) >= 6
        else "low"
    )
    return {
        "repository": resolved["repository"],
        "symbol": symbol,
        "definitions": definitions.get("definitions", []),
        "references": references.get("references", []),
        "callers": callers.get("callers", []),
        "reference_count": references.get("total_references", 0),
        "caller_count": callers.get("total_callers", 0),
        "impacted_files": [{"path": path, "match_count": count} for path, count in impacted_files.most_common(15)],
        "related_symbols": related_symbols,
        "risk": risk,
        "suggested_review_files": related_paths[:10],
        "resolution_backend": "native_graph+fallback" if graph_impact else "snapshot_fallback",
        "native_graph_impact": graph_impact or {},
    }


async def get_graph_summary(*, db, repository_id: str | None, cwd: Path, project_id: str | None) -> dict[str, Any]:
    resolved = await _get_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)
    return _graph_summary_payload(resolved)


async def _reference_text_matches(
    snapshot: dict[str, Any], *, repo_root: Path, symbol: str, limit: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """SCIP references when the snapshot has them, else a whole-word text search."""
    scip_refs = (
        _scip_references(snapshot, symbol=symbol)
        if snapshot.get("engines", {}).get("semantic_backend") == "scip"
        else []
    )
    text_matches = (
        {"backend": "scip", "results": scip_refs}
        if scip_refs
        else await _search_repository_text(
            snapshot, repo_root=repo_root, query=rf"\b{re.escape(symbol)}\b", limit=limit, case_sensitive=True
        )
    )
    return scip_refs, text_matches


def _merge_lsp_references(
    references: list[dict[str, Any]], lsp_references: list[dict[str, Any]], *, definition_keys: set[Any]
) -> None:
    seen_refs = {
        (str(item.get("path") or ""), int(item.get("line") or 0), int(item.get("column") or 0)) for item in references
    }
    for item in lsp_references:
        key = (str(item.get("path") or ""), int(item.get("line") or 0), int(item.get("column") or 0))
        if key not in seen_refs:
            seen_refs.add(key)
            references.append(
                {**item, "is_definition": (item.get("path"), int(item.get("line") or 0)) in definition_keys}
            )
