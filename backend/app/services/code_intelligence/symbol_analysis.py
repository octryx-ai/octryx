"""Symbol lookup and LSP helpers for code intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.lsp import _detect_language as _detect_lsp_language

from .storage_constants import _LANGUAGE_TO_LSP_LANGUAGE
from .storage_search import (
    _iter_source_files,
    _language_for_path,
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
