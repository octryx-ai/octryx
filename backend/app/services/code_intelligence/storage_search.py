"""Text and symbol search helpers for code intelligence storage."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from app.services.code_intelligence.storage_capabilities import _binary_available, _find_binary
from app.services.code_intelligence.storage_constants import _IGNORE_DIRS, _SOURCE_EXTENSIONS, _SYMBOL_PATTERNS
from app.services.code_intelligence.storage_runtime import _coerce_dict, _coerce_list, _truncate


def _language_for_path(path: Path) -> str | None:
    return _SOURCE_EXTENSIONS.get(path.suffix.lower())


def _iter_source_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = [item for item in dirs if item not in _IGNORE_DIRS and not item.startswith(".cache")]
        base = Path(root)
        for filename in filenames:
            path = base / filename
            language = _language_for_path(path)
            if not language:
                continue
            try:
                if path.stat().st_size > 512_000:
                    continue
            except OSError:
                continue
            files.append(path)
    return sorted(files)


def _is_ignored_relative_path(path: str) -> bool:
    parts = Path(path).parts
    return any(part in _IGNORE_DIRS for part in parts)


def _line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _extract_symbols(text: str, *, language: str, relative_path: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for kind, pattern in _SYMBOL_PATTERNS.get(language, []):
        for match in pattern.finditer(text):
            name = next((group for group in match.groups() if group), "")
            if not name:
                continue
            line = _line_number_for_offset(text, match.start())
            key = (name, line, kind)
            if key in seen:
                continue
            seen.add(key)
            snippet = text[max(0, match.start() - 80) : match.end() + 120].splitlines()[0].strip()
            symbols.append(
                {
                    "name": name,
                    "kind": kind,
                    "path": relative_path,
                    "line": line,
                    "column": 1,
                    "language": language,
                    "signature": _truncate(snippet, max_chars=220),
                }
            )
    return symbols


def _manual_search(repo_root: Path, *, query: str, limit: int, case_sensitive: bool = False) -> list[dict[str, Any]]:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)
    matches: list[dict[str, Any]] = []
    for path in _iter_source_files(repo_root):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(content.splitlines(), start=1):
            if not pattern.search(line):
                continue
            matches.append(
                {
                    "path": str(path.relative_to(repo_root)),
                    "line": line_no,
                    "column": 1,
                    "preview": _truncate(line.strip(), max_chars=240),
                }
            )
            if len(matches) >= limit:
                return matches
    return matches


def _zoekt_artifact_ready(snapshot: dict[str, Any]) -> bool:
    artifacts = _coerce_dict(_coerce_dict(snapshot.get("artifacts")).get("zoekt"))
    return str(artifacts.get("status") or "").strip().lower() == "ready"


def _zoekt_index_root(snapshot: dict[str, Any]) -> Path | None:
    artifacts = _coerce_dict(_coerce_dict(snapshot.get("artifacts")).get("zoekt"))
    index_dir = str(artifacts.get("index_dir") or "").strip()
    if not index_dir:
        return None
    try:
        path = Path(index_dir).resolve()
    except Exception:
        return None
    return path if path.exists() and path.is_dir() else None


def _normalize_zoekt_match(entry: dict[str, Any], *, repo_root: Path) -> list[dict[str, Any]]:
    file_name = str(entry.get("FileName") or entry.get("fileName") or "").strip()
    if not file_name:
        return []
    line_matches = _coerce_list(entry.get("LineMatches") or entry.get("lineMatches"))
    if not line_matches:
        return [{"path": file_name, "line": 1, "column": 1, "preview": ""}]
    normalized: list[dict[str, Any]] = []
    for item in line_matches:
        if not isinstance(item, dict):
            continue
        line_text = item.get("Line") or item.get("line") or ""
        if isinstance(line_text, bytes):
            preview = line_text.decode("utf-8", errors="replace")
        else:
            preview = str(line_text or "")
            if preview:
                try:
                    decoded = base64.b64decode(preview, validate=True)
                    if decoded:
                        preview = decoded.decode("utf-8", errors="replace")
                except Exception:
                    pass
        line_fragments = _coerce_list(item.get("LineFragments") or item.get("lineFragments"))
        column = 1
        if line_fragments and isinstance(line_fragments[0], dict):
            column = int(line_fragments[0].get("LineOffset") or line_fragments[0].get("lineOffset") or 0) + 1
        normalized.append(
            {
                "path": file_name,
                "line": int(item.get("LineNumber") or item.get("lineNumber") or 1),
                "column": column,
                "preview": _truncate(preview.strip(), max_chars=240),
            }
        )
    return normalized


async def _search_zoekt(snapshot: dict[str, Any], *, repo_root: Path, query: str, limit: int) -> dict[str, Any] | None:
    zoekt_binary = _find_binary("zoekt")
    index_root = _zoekt_index_root(snapshot)
    if not zoekt_binary or index_root is None or not _zoekt_artifact_ready(snapshot):
        return None
    command = [zoekt_binary, "-index_dir", str(index_root), "-jsonl", query]
    proc = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _stderr = await proc.communicate()
    if proc.returncode != 0:
        # The search engine's stderr (index paths, the query) is never kept: closed code and exit status.
        return {
            "backend": "zoekt",
            "results": [],
            "error": f"zoekt_search_failed exit_code={proc.returncode}",
            "error_code": "zoekt_search_failed",
            "exit_code": proc.returncode,
        }
    results: list[dict[str, Any]] = []
    for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        results.extend(_normalize_zoekt_match(payload, repo_root=repo_root))
        if len(results) >= limit:
            break
    return {"backend": "zoekt", "results": results[:limit]}


async def _search_text(repo_root: Path, *, query: str, limit: int, case_sensitive: bool = False) -> dict[str, Any]:
    if _binary_available("rg"):
        command = [
            "rg",
            "--line-number",
            "--column",
            "--no-heading",
            "--color",
            "never",
            *(["--case-sensitive"] if case_sensitive else ["--ignore-case"]),
            query,
            str(repo_root),
        ]
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _stderr = await proc.communicate()
        if proc.returncode in {0, 1}:
            results: list[dict[str, Any]] = []
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.split(":", 3)
                if len(parts) != 4:
                    continue
                file_path, line_no, col_no, preview = parts
                try:
                    rel = Path(file_path).resolve().relative_to(repo_root)
                except ValueError:
                    rel = Path(file_path)
                if _is_ignored_relative_path(str(rel)):
                    continue
                results.append(
                    {
                        "path": str(rel),
                        "line": int(line_no or 1),
                        "column": int(col_no or 1),
                        "preview": _truncate(preview.strip(), max_chars=240),
                    }
                )
                if len(results) >= limit:
                    break
            # ripgrep stderr (unreadable paths, permission errors) is diagnostics and never kept.
            return {"backend": "ripgrep", "results": results}
    return {
        "backend": "manual",
        "results": _manual_search(repo_root, query=query, limit=limit, case_sensitive=case_sensitive),
    }


async def _search_repository_text(
    snapshot: dict[str, Any],
    *,
    repo_root: Path,
    query: str,
    limit: int,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    if (
        not case_sensitive
        and str(_coerce_dict(snapshot.get("engines")).get("index_backend") or "").strip().lower() == "zoekt"
    ):
        zoekt_result = await _search_zoekt(snapshot, repo_root=repo_root, query=query, limit=limit)
        if zoekt_result is not None and not zoekt_result.get("error"):
            zoekt_result["results"] = [
                item
                for item in _coerce_list(zoekt_result.get("results"))
                if isinstance(item, dict) and not _is_ignored_relative_path(str(item.get("path") or ""))
            ][:limit]
            return zoekt_result
    return await _search_text(repo_root, query=query, limit=limit, case_sensitive=case_sensitive)
