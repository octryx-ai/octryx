"""Outline query helpers for code intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.services.code_intelligence import get_repository_snapshot
from app.services.code_intelligence.outline import _outline_from_symbols, _python_ast_outline, _tree_sitter_outline
from app.services.code_intelligence.outline_java import _tree_sitter_java_outline
from app.services.code_intelligence.storage_runtime import _coerce_dict, _coerce_list, _truncate
from app.services.code_intelligence.storage_search import _language_for_path
from app.services.code_intelligence.structure import _structure_entry_for_file


async def get_file_outline(
    *,
    db,
    repository_id: str | None,
    cwd: Path,
    project_id: str | None,
    file_path: str,
) -> dict[str, Any]:
    resolved = await get_repository_snapshot(db=db, repository_id=repository_id, cwd=cwd, project_id=project_id)
    snapshot = resolved["snapshot"]
    repo_root = Path(snapshot["repo_root"]).resolve()
    target = (repo_root / file_path).resolve()
    try:
        relative = str(target.relative_to(repo_root))
    except ValueError:
        raise HTTPException(status_code=400, detail="file_path must stay inside the repository root")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {relative}")
    text = target.read_text(encoding="utf-8", errors="replace")
    language = _language_for_path(target) or "unknown"
    structure_entry = _structure_entry_for_file(snapshot, file_path=relative)
    outline = [item for item in _coerce_list(structure_entry.get("outline")) if isinstance(item, dict)]
    backend = str(structure_entry.get("backend") or "").strip().lower() or "regex"
    tree_data = _coerce_dict(structure_entry.get("tree")) or None
    if not outline:
        outline, backend = _fallback_outline(
            target, text=text, language=language, relative=relative, snapshot=snapshot, backend=backend
        )
    if snapshot.get("engines", {}).get("structure_backend") == "tree-sitter" and not tree_data:
        tree_data = await _tree_sitter_outline(target)
        if tree_data and tree_data.get("status") == "ready":
            backend = "tree-sitter"
    sorted_outline = sorted(outline, key=lambda item: (int(item.get("line") or 1), str(item.get("name") or "")))
    return {
        "repository": resolved["repository"],
        "file_path": relative,
        "language": language,
        "structure_backend": backend,
        "outline": sorted_outline,
        "chunks": _outline_chunks(sorted_outline, text=text),
        "tree": tree_data,
    }


def _fallback_outline(
    target: Path, *, text: str, language: str, relative: str, snapshot: dict[str, Any], backend: str
) -> tuple[list[dict[str, Any]], str]:
    """Parse the file directly when the structure index has no outline for it."""
    outline: list[dict[str, Any]] = []
    if language == "python":
        outline = _python_ast_outline(target, text)
        if outline:
            backend = "python_ast"
    elif language == "java":
        outline = _tree_sitter_java_outline(target, text)
        if outline:
            backend = "tree-sitter"
    if not outline:
        outline = _outline_from_symbols(symbols=_coerce_list(snapshot.get("symbols")), file_path=relative)
    return outline, backend


def _outline_chunks(sorted_outline: list[dict[str, Any]], *, text: str) -> list[dict[str, Any]]:
    chunks = []
    for item in sorted_outline:
        start = max(1, int(item.get("line") or 1))
        end = max(start, int(item.get("end_line") or start))
        snippet_lines = text.splitlines()[start - 1 : min(end, start + 20)]
        chunks.append(
            {
                "name": item.get("name"),
                "kind": item.get("kind"),
                "line": start,
                "end_line": end,
                "snippet": _truncate("\n".join(snippet_lines), max_chars=500),
            }
        )
    return chunks
