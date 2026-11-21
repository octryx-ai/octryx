"""Structure index helpers for code intelligence."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.services.code_intelligence.storage_runtime import _coerce_dict, _coerce_list, _now_iso, _structure_artifact_dir

OutlineBuilder = Callable[[Path, str], list[dict[str, Any]]]
SymbolOutlineBuilder = Callable[..., list[dict[str, Any]]]
TreeOutlineBuilder = Callable[[Path], Awaitable[dict[str, Any] | None]]


def _read_structure_index(snapshot: dict[str, Any]) -> dict[str, Any]:
    artifact = _coerce_dict(_coerce_dict(snapshot.get("artifacts")).get("tree_sitter"))
    path = str(artifact.get("index_path") or "").strip()
    if not path:
        return {}
    try:
        return _coerce_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception:
        return {}


def _structure_entry_for_file(snapshot: dict[str, Any], *, file_path: str) -> dict[str, Any]:
    structure_index = _read_structure_index(snapshot)
    for item in _coerce_list(structure_index.get("files")):
        if isinstance(item, dict) and str(item.get("path") or "").strip() == file_path:
            return item
    return {}


async def _maybe_build_structure_index(
    *,
    repository_id: str,
    repo_root: Path,
    snapshot: dict[str, Any],
    python_outline_builder: OutlineBuilder,
    java_outline_builder: OutlineBuilder,
    symbol_outline_builder: SymbolOutlineBuilder,
    tree_outline_builder: TreeOutlineBuilder,
) -> dict[str, Any]:
    output_dir = _structure_artifact_dir(repository_id)
    manifest_path = output_dir / "index.json"
    file_items = [item for item in _coerce_list(snapshot.get("files")) if isinstance(item, dict)]
    allow_raw_tree = len(file_items) <= 250
    files_manifest: list[dict[str, Any]] = []
    for item in file_items:
        entry = await _structure_file_entry(
            item,
            repo_root=repo_root,
            snapshot=snapshot,
            allow_raw_tree=allow_raw_tree,
            file_count=len(file_items),
            python_outline_builder=python_outline_builder,
            java_outline_builder=java_outline_builder,
            symbol_outline_builder=symbol_outline_builder,
            tree_outline_builder=tree_outline_builder,
        )
        if entry is not None:
            files_manifest.append(entry)
    manifest = {
        "generated_at": _now_iso(),
        "file_count": len(files_manifest),
        "raw_tree_enabled": allow_raw_tree,
        "files": files_manifest,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "status": "ready" if files_manifest else "skipped",
        "output_dir": str(output_dir),
        "index_path": str(manifest_path),
        "file_count": len(files_manifest),
        "raw_tree_enabled": allow_raw_tree,
    }


async def _structure_file_entry(
    item: dict[str, Any],
    *,
    repo_root: Path,
    snapshot: dict[str, Any],
    allow_raw_tree: bool,
    file_count: int,
    python_outline_builder: OutlineBuilder,
    java_outline_builder: OutlineBuilder,
    symbol_outline_builder: SymbolOutlineBuilder,
    tree_outline_builder: TreeOutlineBuilder,
) -> dict[str, Any] | None:
    relative = str(item.get("path") or "").strip()
    if not relative:
        return None
    target = repo_root / relative
    if not target.exists() or not target.is_file():
        return None
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    language = str(item.get("language") or "").strip() or "unknown"
    outline: list[dict[str, Any]] = []
    tree = None
    backend = "regex"
    if language == "python":
        outline = python_outline_builder(target, text)
        if outline:
            backend = "python_ast"
    elif language == "java":
        outline = java_outline_builder(target, text)
        if outline:
            backend = "tree-sitter"
    if not outline:
        outline = symbol_outline_builder(symbols=_coerce_list(snapshot.get("symbols")), file_path=relative)
    if allow_raw_tree:
        tree = await tree_outline_builder(target)
    else:
        tree = {"status": "skipped", "reason": "repo_too_large_for_raw_tree", "file_count": file_count}
    if tree and tree.get("status") == "ready":
        backend = "tree-sitter"
    return {"path": relative, "language": language, "backend": backend, "outline": outline, "tree": tree}
