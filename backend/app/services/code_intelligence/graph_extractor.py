"""Deterministic native code graph extraction orchestration."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.code_intelligence.graph_file_metadata import build_file_extraction_metadata
from app.services.code_intelligence.graph_imports import (
    build_module_index,
    extract_import_targets,
    language_for_file_item,
    resolve_import_target,
)
from app.services.code_intelligence.graph_language_extractors import extract_calls, extract_routes, extract_symbols
from app.services.code_intelligence.graph_primitives import file_id, unresolved_reference
from app.services.code_intelligence.storage_runtime import _coerce_list


def build_native_code_graph_payload(*, repo_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    file_items = [item for item in _coerce_list(snapshot.get("files")) if isinstance(item, dict)]
    module_index = build_module_index(file_items)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    symbol_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    symbol_by_id: dict[str, dict[str, Any]] = {}
    file_texts: dict[str, str] = {}

    for item in file_items:
        relative_path = str(item.get("path") or "").strip()
        if not relative_path:
            continue
        language = str(item.get("language") or "").strip() or "unknown"
        text = _read_text(repo_root / relative_path)
        file_texts[relative_path] = text
        nodes.append(_file_node(relative_path=relative_path, language=language, text=text, item=item))
        for symbol in extract_symbols(relative_path=relative_path, language=language, text=text):
            nodes.append(symbol)
            symbol_by_id[symbol["id"]] = symbol
            _index_symbol(symbol_index, symbol)
            edges.extend(_symbol_edges(relative_path, symbol))

    for relative_path, text in file_texts.items():
        language = language_for_file_item(file_items, relative_path)
        _append_import_edges(
            edges=edges,
            unresolved=unresolved,
            relative_path=relative_path,
            language=language,
            text=text,
            module_index=module_index,
        )
        for route in extract_routes(relative_path=relative_path, language=language, text=text, symbol_index=symbol_index):
            nodes.append(route["node"])
            edges.append(route["edge"])
        _append_call_edges(
            edges=edges,
            unresolved=unresolved,
            relative_path=relative_path,
            language=language,
            text=text,
            symbol_index=symbol_index,
            symbol_by_id=symbol_by_id,
        )

    return {
        "backend": "code_graph",
        "extractor": "native",
        "node_count": len(nodes),
        "edge_count": len(_dedupe_edges(edges)),
        "unresolved_reference_count": len(unresolved),
        "nodes": _dedupe_nodes(nodes),
        "edges": _dedupe_edges(edges),
        "unresolved_references": unresolved,
    }


def _file_node(*, relative_path: str, language: str, text: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": file_id(relative_path),
        "kind": "file",
        "label": relative_path,
        "language": language,
        "path": relative_path,
        "line_count": int(item.get("line_count") or _line_count(text)),
        "size_bytes": int(item.get("size_bytes") or len(text.encode("utf-8"))),
        "metadata": {
            "extractor": "native",
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            **build_file_extraction_metadata(relative_path=relative_path, language=language, text=text),
        },
    }


def _index_symbol(symbol_index: dict[str, list[dict[str, Any]]], symbol: dict[str, Any]) -> None:
    label = str(symbol.get("label") or "").lower()
    symbol_index[label].append(symbol)
    qualified = str(symbol.get("qualified_name") or "").lower()
    if qualified and qualified != label:
        symbol_index[qualified].append(symbol)


def _symbol_edges(relative_path: str, symbol: dict[str, Any]) -> list[dict[str, Any]]:
    edges = [
        {
            "source": file_id(relative_path),
            "target": symbol["id"],
            "kind": "defines",
            "label": str(symbol.get("label") or ""),
            "confidence": "EXTRACTED",
            "metadata": {"extractor": str(symbol.get("backend") or "native")},
        }
    ]
    parent_id = str(symbol.get("parent_id") or "")
    if parent_id:
        edges.append(
            {
                "source": parent_id,
                "target": symbol["id"],
                "kind": "contains",
                "label": str(symbol.get("label") or ""),
                "confidence": "EXTRACTED",
                "metadata": {"extractor": str(symbol.get("backend") or "native")},
            }
        )
    return edges


def _append_import_edges(
    *,
    edges: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    relative_path: str,
    language: str,
    text: str,
    module_index: dict[str, str],
) -> None:
    for target in extract_import_targets(text, language=language):
        resolved_path = resolve_import_target(
            target,
            language=language,
            module_index=module_index,
            source_path=relative_path,
        )
        if resolved_path:
            edges.append(
                {
                    "source": file_id(relative_path),
                    "target": file_id(resolved_path),
                    "kind": "imports",
                    "label": target,
                    "confidence": "EXTRACTED",
                    "metadata": {"extractor": "native_imports"},
                }
            )
        else:
            unresolved.append(unresolved_reference(relative_path, target, "import", 0, "import_target_not_found"))


def _append_call_edges(
    *,
    edges: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    relative_path: str,
    language: str,
    text: str,
    symbol_index: dict[str, list[dict[str, Any]]],
    symbol_by_id: dict[str, dict[str, Any]],
) -> None:
    for call in extract_calls(relative_path=relative_path, language=language, text=text, symbol_by_id=symbol_by_id):
        candidates = symbol_index.get(str(call["target"]).lower(), [])
        if len(candidates) == 1:
            edges.append(
                {
                    "source": call["source"],
                    "target": candidates[0]["id"],
                    "kind": "calls",
                    "label": call["target"],
                    "confidence": "EXTRACTED",
                    "metadata": {"extractor": call["extractor"], "line": call["line"]},
                }
            )
        elif candidates:
            unresolved.append(unresolved_reference(relative_path, call["target"], "call", call["line"], "ambiguous_call_target"))
        else:
            unresolved.append(unresolved_reference(relative_path, call["target"], "call", call["line"], "call_target_not_found"))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _line_count(text: str) -> int:
    return text.count("\n") + 1 if text else 0


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        result.append(node)
    return result


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for edge in edges:
        key = (str(edge.get("source") or ""), str(edge.get("target") or ""), str(edge.get("kind") or ""))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


__all__ = ["build_native_code_graph_payload"]
