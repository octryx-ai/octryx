"""Repository snapshot of source files and regex symbols for code intelligence."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .storage_runtime import _now_iso
from .storage_search import _extract_symbols, _iter_source_files, _language_for_path


def _build_snapshot(
    repo_root: Path,
    *,
    capabilities: dict[str, Any],
    index_backend: str,
    semantic_backend: str,
    structure_backend: str,
    graph_backend: str,
) -> dict[str, Any]:
    files = _iter_source_files(repo_root)
    language_counter: Counter[str] = Counter()
    snapshot_files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    for path in files:
        relative = str(path.relative_to(repo_root))
        language = _language_for_path(path) or "unknown"
        language_counter[language] += 1
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snapshot_files.append(
            {
                "path": relative,
                "language": language,
                "line_count": content.count("\n") + 1,
                "size_bytes": len(content.encode("utf-8")),
            }
        )
        symbols.extend(_extract_symbols(content, language=language, relative_path=relative))
    return {
        "repo_root": str(repo_root),
        "generated_at": _now_iso(),
        "engines": {
            "index_backend": index_backend,
            "semantic_backend": semantic_backend,
            "structure_backend": structure_backend,
            "graph_backend": graph_backend,
        },
        "capabilities": capabilities,
        "languages": dict(language_counter),
        "files": snapshot_files,
        "symbols": symbols,
        "file_count": len(snapshot_files),
        "symbol_count": len(symbols),
    }
