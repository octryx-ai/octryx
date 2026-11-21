"""Symbol lookup and LSP helpers for code intelligence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.code_intelligence.semantic_store import _read_native_scip_index, _read_semantic_index
from app.services.lsp import _detect_language as _detect_lsp_language

from .storage_constants import _LANGUAGE_TO_LSP_LANGUAGE
from .storage_runtime import _coerce_dict, _coerce_list, _truncate
from .storage_search import (
    _iter_source_files,
    _language_for_path,
    _line_number_for_offset,
)


def _get_lsp_manager():
    from ..lsp import lsp_manager

    return lsp_manager


def _rank_symbol(symbol: dict[str, Any], query: str) -> tuple[int, int]:
    name = str(symbol.get("name") or "")
    lowered = query.lower()
    exact = 0 if name.lower() == lowered else 1
    position = name.lower().find(lowered)
    return (exact, position if position >= 0 else 9999)


def _normalize_lsp_path_for_repo(path: str, *, repo_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(repo_root))
    except Exception:
        return str(path or "").strip()


async def _lsp_workspace_symbol_matches(
    *,
    repo_root: Path,
    symbol: str,
    project_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    languages = sorted({_language_for_path(path) for path in _iter_source_files(repo_root) if _language_for_path(path)})
    for language in languages:
        lsp_language = _LANGUAGE_TO_LSP_LANGUAGE.get(language)
        if not lsp_language:
            continue
        try:
            client = await _get_lsp_manager().get_or_create(
                lsp_language, str(repo_root), project_config=project_config or {}
            )
        except Exception:
            continue
        if client is None:
            continue
        try:
            matches = await client.workspace_symbols(symbol)
        except Exception:
            continue
        for item in matches:
            name = str(item.get("name") or "").strip()
            path = _normalize_lsp_path_for_repo(str(item.get("path") or ""), repo_root=repo_root)
            line = int(item.get("line") or 1)
            key = (path, line, name)
            if not name or key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "name": name,
                    "kind": f"lsp:{item.get('kind')}",
                    "path": path,
                    "line": line,
                    "column": int(item.get("col") or 1),
                    "language": language,
                    "signature": name,
                    "backend": "lsp",
                }
            )
    return results


async def _lsp_references_for_definition(
    *,
    repo_root: Path,
    definition: dict[str, Any],
    include_declaration: bool = True,
    project_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    path = repo_root / str(definition.get("path") or "")
    if not path.exists() or not path.is_file():
        return []
    language = _detect_lsp_language(str(path))
    if not language:
        return []
    try:
        client = await _get_lsp_manager().get_or_create(language, str(repo_root), project_config=project_config or {})
    except Exception:
        return []
    if client is None:
        return []
    try:
        locations = await client.find_references(
            str(path),
            int(definition.get("line") or 1),
            int(definition.get("column") or 1),
            include_declaration=include_declaration,
        )
    except Exception:
        return []
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for item in locations:
        normalized_path = _normalize_lsp_path_for_repo(str(item.get("path") or ""), repo_root=repo_root)
        line = int(item.get("line") or 1)
        column = int(item.get("col") or 1)
        key = (normalized_path, line, column)
        if not normalized_path or key in seen:
            continue
        seen.add(key)
        results.append({"path": normalized_path, "line": line, "column": column, "preview": "", "backend": "lsp"})
    return results


def _scip_definitions(snapshot: dict[str, Any], *, symbol: str) -> list[dict[str, Any]]:
    native_java = _read_native_scip_index(snapshot, language="java")
    native_definitions = _coerce_dict(native_java.get("definitions_by_name")).get(symbol.lower())
    if isinstance(native_definitions, list):
        return [item for item in native_definitions if isinstance(item, dict)]
    semantic_index = _read_semantic_index(snapshot)
    definitions = _coerce_dict(semantic_index.get("definitions_by_symbol")).get(symbol.lower())
    if not isinstance(definitions, list):
        return []
    return [item for item in definitions if isinstance(item, dict)]


def _scip_references(snapshot: dict[str, Any], *, symbol: str) -> list[dict[str, Any]]:
    native_java = _read_native_scip_index(snapshot, language="java")
    if native_java:
        native_results = _native_scip_references(native_java, symbol=symbol)
        if native_results:
            return native_results

    semantic_index = _read_semantic_index(snapshot)
    references = _coerce_dict(semantic_index.get("references_by_symbol")).get(symbol.lower())
    if isinstance(references, list):
        return [item for item in references if isinstance(item, dict)]
    return _text_scip_references(snapshot, semantic_index=semantic_index, symbol=symbol)


def _native_scip_references(native_java: dict[str, Any], *, symbol: str) -> list[dict[str, Any]]:
    definitions = [
        item
        for item in _coerce_dict(native_java.get("definitions_by_name")).get(symbol.lower(), [])
        if isinstance(item, dict)
    ]
    if not definitions:
        return []
    symbol_ids = {
        str(item.get("symbol_id") or "").strip()
        for item in definitions
        if str(item.get("symbol_id") or "").strip()
    }
    results: list[dict[str, Any]] = []
    for symbol_id in symbol_ids:
        for item in _coerce_dict(native_java.get("references_by_symbol")).get(symbol_id, []):
            if isinstance(item, dict):
                results.append(item)
    return results


def _text_scip_references(
    snapshot: dict[str, Any], *, semantic_index: dict[str, Any], symbol: str
) -> list[dict[str, Any]]:
    """Plain word-boundary search over files in SCIP-ready languages when no reference index exists."""
    repo_root = Path(str(snapshot.get("repo_root") or "."))
    target_name = symbol.strip()
    if not target_name:
        return []
    pattern = re.compile(rf"\b{re.escape(target_name)}\b")
    results: list[dict[str, Any]] = []
    for file_entry in _coerce_list(snapshot.get("files")):
        if not isinstance(file_entry, dict):
            continue
        language = str(file_entry.get("language") or "").strip()
        if language not in set(_coerce_list(semantic_index.get("languages"))):
            continue
        relative_path = str(file_entry.get("path") or "").strip()
        if not relative_path:
            continue
        absolute = repo_root / relative_path
        try:
            content = absolute.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = content.splitlines()
        for match in pattern.finditer(content):
            line = _line_number_for_offset(content, match.start())
            preview = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            results.append(
                {
                    "path": relative_path,
                    "line": line,
                    "column": int(match.start() - content.rfind("\n", 0, match.start())),
                    "preview": _truncate(preview, max_chars=240),
                    "backend": "scip",
                }
            )
    return results
