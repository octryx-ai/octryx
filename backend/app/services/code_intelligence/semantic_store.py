"""Semantic artifact parsing and persistence helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.code_intelligence.storage_constants import (
    _SCIP_SNAPSHOT_METADATA_PATTERN,
    _SCIP_SNAPSHOT_OCCURRENCE_PATTERN,
)
from app.services.code_intelligence.storage_runtime import (
    _coerce_dict,
    _coerce_list,
    _now_iso,
    _scip_index_dir,
    _truncate,
)
from app.services.code_intelligence.storage_search import _language_for_path


def _scip_output_candidates(repo_root: Path) -> list[Path]:
    return [repo_root / "index.scip", repo_root / "dump.scip"]


def _scip_stage_dir(repository_id: str, language: str) -> Path:
    stage_dir = _scip_index_dir(repository_id) / "_staging" / language
    stage_dir.mkdir(parents=True, exist_ok=True)
    return stage_dir


def _finalize_scip_output(
    *, repo_root: Path, output_dir: Path, language: str, staged_output_path: Path | None = None
) -> str | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[Path] = []
    if staged_output_path is not None:
        candidates.append(staged_output_path)
    candidates.extend(_scip_output_candidates(repo_root))
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        target = output_dir / f"{language}.scip"
        if target.exists():
            target.unlink()
        candidate.replace(target)
        return str(target)
    return None


def _semantic_artifact_path(repository_id: str) -> Path:
    return _scip_index_dir(repository_id) / "semantic_index.json"


def _build_semantic_index(snapshot: dict[str, Any], *, ready_languages: set[str]) -> dict[str, Any]:
    files = [item for item in _coerce_list(snapshot.get("files")) if isinstance(item, dict)]
    symbols = [
        item
        for item in _coerce_list(snapshot.get("symbols"))
        if isinstance(item, dict) and str(item.get("language") or "").strip() in ready_languages
    ]
    file_map = {str(item.get("path") or ""): item for item in files}
    definitions_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    symbol_records: list[dict[str, Any]] = []
    for symbol in symbols:
        name = str(symbol.get("name") or "").strip()
        path = str(symbol.get("path") or "").strip()
        if not name or not path:
            continue
        lowered = name.lower()
        record = {
            "name": name,
            "normalized_name": lowered,
            "path": path,
            "line": int(symbol.get("line") or 1),
            "column": int(symbol.get("column") or 1),
            "kind": str(symbol.get("kind") or ""),
            "language": str(symbol.get("language") or ""),
            "signature": str(symbol.get("signature") or ""),
            "backend": "scip",
        }
        if path in file_map:
            record["file"] = file_map[path]
        symbol_records.append(record)
        definitions_by_symbol[lowered].append(record)
    return {
        "generated_at": _now_iso(),
        "languages": sorted(ready_languages),
        "definitions": symbol_records,
        "definitions_by_symbol": dict(definitions_by_symbol),
        "references_by_symbol": {},
    }


def _write_semantic_index(*, repository_id: str, semantic_index: dict[str, Any]) -> str:
    output_path = _semantic_artifact_path(repository_id)
    output_path.write_text(json.dumps(semantic_index, indent=2), encoding="utf-8")
    return str(output_path)


def _read_semantic_index(snapshot: dict[str, Any]) -> dict[str, Any]:
    artifact = _coerce_dict(_coerce_dict(snapshot.get("artifacts")).get("scip"))
    path = str(artifact.get("semantic_index_path") or "").strip()
    if not path:
        return {}
    try:
        return _coerce_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception:
        return {}


def _read_native_scip_index(snapshot: dict[str, Any], *, language: str) -> dict[str, Any]:
    artifact = _coerce_dict(_coerce_dict(snapshot.get("artifacts")).get("scip"))
    path = str(_coerce_dict(artifact.get("native_index_paths")).get(language) or "").strip()
    if not path:
        return {}
    try:
        return _coerce_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception:
        return {}


def _is_scip_snapshot_annotation_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.startswith("//"):
        return False
    return bool(_SCIP_SNAPSHOT_OCCURRENCE_PATTERN.match(line) or _SCIP_SNAPSHOT_METADATA_PATTERN.match(line))


def _parse_scip_snapshot_annotations(snapshot_root: Path) -> dict[str, Any]:
    definitions_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    definitions_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    references_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    symbol_meta: dict[str, dict[str, Any]] = {}
    sinks = (definitions_by_name, definitions_by_symbol, references_by_symbol, symbol_meta)
    files_indexed = 0
    for target in sorted(snapshot_root.rglob("*")):
        if not target.is_file():
            continue
        relative_path = str(target.relative_to(snapshot_root))
        language = _language_for_path(target) or "unknown"
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        files_indexed += 1
        _scan_snapshot_lines(lines, relative_path=relative_path, language=language, sinks=sinks)
    return {
        "generated_at": _now_iso(),
        "files_indexed": files_indexed,
        "definitions_by_name": dict(definitions_by_name),
        "definitions_by_symbol": dict(definitions_by_symbol),
        "references_by_symbol": dict(references_by_symbol),
        "symbol_meta": symbol_meta,
    }


def _scan_snapshot_lines(lines: list[str], *, relative_path: str, language: str, sinks: tuple[Any, ...]) -> None:
    """Walk one annotated snapshot file, tracking the source line each occurrence comment points at."""
    source_line = 0
    last_source_line = 1
    last_source_text = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        occurrence_match = _SCIP_SNAPSHOT_OCCURRENCE_PATTERN.match(line)
        if occurrence_match:
            occurrence_kind = str(occurrence_match.group("kind") or "").strip()
            symbol_id = str(occurrence_match.group("symbol") or "").strip()
            column = max(1, line.find("^") - line.find("//") - 2) if "^" in line else 1
            metadata, lookahead = _read_occurrence_metadata(lines, index + 1)
            record = {
                "symbol_id": symbol_id,
                "path": relative_path,
                "line": max(1, last_source_line),
                "column": max(1, column),
                "preview": _truncate(last_source_text.strip(), max_chars=240),
                "language": language,
                "backend": "scip_native",
            }
            _store_occurrence(occurrence_kind, symbol_id=symbol_id, record=record, metadata=metadata, sinks=sinks)
            index = lookahead
            continue
        if not _is_scip_snapshot_annotation_line(line):
            source_line += 1
            last_source_line = source_line
            last_source_text = line
        index += 1


def _read_occurrence_metadata(lines: list[str], lookahead: int) -> tuple[dict[str, str], int]:
    metadata: dict[str, str] = {}
    while lookahead < len(lines):
        meta_match = _SCIP_SNAPSHOT_METADATA_PATTERN.match(lines[lookahead])
        if not meta_match:
            break
        metadata[str(meta_match.group("key"))] = str(meta_match.group("value") or "").strip()
        lookahead += 1
    return metadata, lookahead


def _store_occurrence(
    occurrence_kind: str,
    *,
    symbol_id: str,
    record: dict[str, Any],
    metadata: dict[str, str],
    sinks: tuple[Any, ...],
) -> None:
    definitions_by_name, definitions_by_symbol, references_by_symbol, symbol_meta = sinks
    if occurrence_kind != "definition":
        references_by_symbol[symbol_id].append({**record, "is_definition": False})
        return
    definition = {
        **record,
        "name": metadata.get("display_name") or symbol_id,
        "normalized_name": (metadata.get("display_name") or symbol_id).lower(),
        "signature": metadata.get("signature_documentation") or metadata.get("display_name") or symbol_id,
        "kind": (metadata.get("kind") or "symbol").lower(),
    }
    definitions_by_name[definition["normalized_name"]].append(definition)
    definitions_by_symbol[symbol_id].append(definition)
    symbol_meta[symbol_id] = {
        "display_name": definition["name"],
        "signature": definition["signature"],
        "kind": definition["kind"],
    }
