"""Shared node and edge primitives for native Code Graph extraction."""

from __future__ import annotations

from typing import Any

from app.services.code_intelligence.storage_runtime import _truncate

CALL_KEYWORDS = {
    "catch",
    "for",
    "if",
    "new",
    "return",
    "switch",
    "while",
}


def symbol_node(
    *,
    relative_path: str,
    language: str,
    symbol_id: str,
    name: str,
    qualified_name: str,
    kind: str,
    line: int,
    end_line: int,
    signature: str,
    backend: str,
    parent_id: str = "",
) -> dict[str, Any]:
    return {
        "id": symbol_id,
        "kind": kind,
        "label": name,
        "qualified_name": qualified_name,
        "language": language,
        "path": relative_path,
        "line": line,
        "line_end": end_line,
        "signature": signature,
        "backend": backend,
        "parent_id": parent_id,
        "metadata": {"extractor": backend, "qualified_name": qualified_name},
    }


def script_signature(line: str) -> str:
    return _truncate(line.strip(), max_chars=220)


def route_node(relative_path: str, framework: str, method: str, route_path: str, line: int) -> dict[str, Any]:
    label = f"{method} {route_path}"
    return {
        "id": f"route:{framework}:{method}:{route_path}:{relative_path}:{line}",
        "kind": "route",
        "label": label,
        "language": "route",
        "path": relative_path,
        "line": line,
        "line_end": line,
        "signature": label,
        "backend": "route_extractor",
        "metadata": {"framework": framework, "method": method, "route_path": route_path, "extractor": "native_routes"},
    }


def route_edge(route_id: str, target_id: str, handler: str) -> dict[str, Any]:
    return {
        "source": route_id,
        "target": target_id,
        "kind": "routes_to",
        "label": handler,
        "confidence": "EXTRACTED",
        "metadata": {"extractor": "native_routes"},
    }


def single_symbol(symbol_index: dict[str, list[dict[str, Any]]], name: str) -> dict[str, Any] | None:
    matches = symbol_index.get(str(name or "").lower(), [])
    return matches[0] if len(matches) == 1 else None


def unresolved_reference(relative_path: str, symbol: str, kind: str, line: int, reason: str) -> dict[str, Any]:
    return {
        "source_path": relative_path,
        "symbol_text": symbol,
        "reference_kind": kind,
        "line": line or None,
        "unresolved_reason": reason,
    }


def file_id(relative_path: str) -> str:
    return f"file:{relative_path}"


def symbol_id(relative_path: str, qualified_name: str, line: int) -> str:
    return f"symbol:{relative_path}:{qualified_name}:{line}"


def line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(offset, 0)) + 1


__all__ = [
    "CALL_KEYWORDS",
    "file_id",
    "line_number_for_offset",
    "route_edge",
    "route_node",
    "script_signature",
    "single_symbol",
    "symbol_id",
    "symbol_node",
    "unresolved_reference",
]
