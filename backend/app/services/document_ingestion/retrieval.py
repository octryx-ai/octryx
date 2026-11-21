from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.document_ingestion.common import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_CHUNK_OVERLAP,
    RESEARCH_WORKSPACE_DIR,
    _read_json,
    _slugify,
)


def _chunk_text(
    text: str, *, chunk_chars: int = DEFAULT_CHUNK_CHARS, overlap: int = DEFAULT_CHUNK_OVERLAP, max_chunks: int = 80
) -> list[dict[str, Any]]:
    normalized = re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()
    if not normalized:
        return []
    size = max(800, int(chunk_chars or DEFAULT_CHUNK_CHARS))
    step = max(400, size - max(0, min(int(overlap or 0), size // 2)))
    chunks = []
    start = 0
    chunk_limit = int(max_chunks or 0)
    while start < len(normalized) and (chunk_limit <= 0 or len(chunks) < chunk_limit):
        end = min(len(normalized), start + size)
        excerpt = normalized[start:end].strip()
        if excerpt:
            chunks.append({"index": len(chunks) + 1, "start_char": start, "end_char": end, "text": excerpt})
        if end >= len(normalized):
            break
        start += step
    return chunks


def _query_tokens(query: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9_-]{2,}", str(query or ""))
        if token.strip()
    }


def _score_chunk(text: str, tokens: set[str]) -> int:
    if not tokens:
        return 0
    lowered = str(text or "").lower()
    return sum(1 for token in tokens if token in lowered)


def _bundle_roots_for_query(workspace_root: Path, bundle_id: str) -> list[Path]:
    candidate_roots = [
        (workspace_root / RESEARCH_WORKSPACE_DIR).resolve(),
    ]
    existing_roots = [root for root in candidate_roots if root.exists()]
    if not existing_roots:
        return []
    explicit = _slugify(bundle_id, fallback="")
    if explicit:
        matches: list[Path] = []
        for root in existing_roots:
            candidate = (root / explicit).resolve()
            if (root == candidate or root in candidate.parents) and candidate.exists():
                matches.append(candidate)
        if matches:
            return matches
        return []
    return sorted(
        (path for root in existing_roots for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _match_record(
    source: dict[str, Any], *, source_id: str, parsed_path: Path, bundle_root: Path, chunk: dict[str, Any],
    chunk_text: str, score: int,
) -> dict[str, Any]:
    return {
        "score": float(score),
        "key": f"{source_id or parsed_path.stem}#parsed-{int(chunk['index']):04d}",
        "source_id": source_id,
        "title": source.get("title") or source.get("file_name") or parsed_path.stem,
        "chunk_index": chunk["index"],
        "excerpt": chunk_text[:900],
        "local_file_path": source.get("local_file_path") or "",
        "parsed_path": str(parsed_path),
        "url": source.get("url") or "",
        "content_id": source.get("content_id") or "",
        "content_sha256": source.get("content_sha256") or "",
        "origin": source.get("origin") or "",
        "bundle_id": source.get("bundle_id") or bundle_root.name,
        "document_version": source.get("document_version") or "",
        "document_version_key": source.get("document_version_key") or "",
    }


def _source_matches(
    source: Any, *, workspace_root: Path, bundle_root: Path, document_id: str, tokens: set[str]
) -> list[tuple[int, dict[str, Any]]] | None:
    """The scored chunks of one source's parsed text; ``None`` when the source is not inspected at all."""
    if not isinstance(source, dict):
        return None
    source_id = str(source.get("id") or "").strip()
    if document_id and source_id != document_id:
        return None
    parsed_path = Path(str(source.get("parsed_path") or "")).expanduser()
    if not parsed_path.is_absolute():
        parsed_path = (workspace_root / parsed_path).resolve()
    if not parsed_path.exists() or not parsed_path.is_file():
        return None
    matches: list[tuple[int, dict[str, Any]]] = []
    text = parsed_path.read_text(encoding="utf-8", errors="replace")
    for chunk in _chunk_text(text, max_chunks=200):
        chunk_text = str(chunk.get("text") or "")
        score = _score_chunk(chunk_text, tokens)
        if score <= 0 and tokens:
            continue
        record = _match_record(source, source_id=source_id, parsed_path=parsed_path, bundle_root=bundle_root,
                               chunk=chunk, chunk_text=chunk_text, score=score)
        matches.append((score, record))
    return matches


def _query_research_bundle(
    *,
    workspace_root: Path,
    bundle_id: str,
    query: str,
    document_id: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    tokens = _query_tokens(query)
    scored_matches: list[tuple[int, dict[str, Any]]] = []
    inspected_sources = 0
    for bundle_root in _bundle_roots_for_query(workspace_root.resolve(), bundle_id):
        sources_payload = _read_json(bundle_root / "sources.json", [])
        if not isinstance(sources_payload, list):
            continue
        for source in sources_payload:
            found = _source_matches(source, workspace_root=workspace_root, bundle_root=bundle_root,
                                    document_id=document_id, tokens=tokens)
            if found is None:
                continue
            inspected_sources += 1
            scored_matches.extend(found)
    scored_matches.sort(key=lambda item: item[0], reverse=True)
    if not scored_matches and inspected_sources:
        return _query_research_bundle(
            workspace_root=workspace_root,
            bundle_id=bundle_id,
            query="",
            document_id=document_id,
            limit=limit,
        )
    matches = [item for _, item in scored_matches[: max(1, min(int(limit or 8), 20))]]
    return {
        "project_id": "",
        "query": query,
        "document_id": document_id,
        "bundle_id": _slugify(bundle_id, fallback=""),
        "total": len(scored_matches),
        "count": len(matches),
        "matches": matches,
        "retrieval_mode": "research_bundle",
    }
