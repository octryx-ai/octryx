"""Line-numbered source chunks for a persisted code graph run."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CodeGraphChunk,
    CodeGraphFile,
    CodeGraphRepository,
    CodeGraphRun,
    CodeGraphSymbol,
)


def _persist_chunk_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    repo_root: Path,
    file_lookup: dict[str, CodeGraphFile],
    graph_symbols: dict[str, CodeGraphSymbol],
) -> None:
    file_texts = _add_file_chunks(
        db=db,
        graph_run=graph_run,
        graph_repo=graph_repo,
        repository_id=repository_id,
        repo_root=repo_root,
        file_lookup=file_lookup,
    )
    for symbol in graph_symbols.values():
        if not symbol.source_file_id or not symbol.line_start:
            continue
        graph_file = next((item for item in file_lookup.values() if item.id == symbol.source_file_id), None)
        if graph_file is None:
            continue
        lines = file_texts.get(graph_file.file_path) or []
        end_line = max(int(symbol.line_start or 1), min(int(symbol.line_end or symbol.line_start or 1), len(lines)))
        content = _line_numbered_slice(lines, start=int(symbol.line_start or 1), end=end_line)
        db.add(
            CodeGraphChunk(
                id=str(uuid4()),
                run_id=graph_run.id,
                graph_repository_id=graph_repo.id,
                code_repository_id=repository_id,
                source_file_id=graph_file.id,
                source_symbol_id=symbol.id,
                chunk_kind="symbol",
                path=graph_file.file_path,
                line_start=int(symbol.line_start or 1),
                line_end=end_line,
                token_estimate=max(1, len(content) // 4) if content else 0,
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None,
                chunk_metadata={"line_numbered": True, "symbol": symbol.qualified_name or symbol.name},
                is_current=True,
            )
        )


def _add_file_chunks(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    repo_root: Path,
    file_lookup: dict[str, CodeGraphFile],
) -> dict[str, list[str]]:
    # The symbol chunks reuse these lines, so each file is read once.
    file_texts: dict[str, list[str]] = {}
    for relative_path, graph_file in file_lookup.items():
        lines = _read_source_lines(repo_root / relative_path)
        file_texts[relative_path] = lines
        content = _line_numbered_slice(lines, start=1, end=min(len(lines), 200))
        db.add(
            CodeGraphChunk(
                id=str(uuid4()),
                run_id=graph_run.id,
                graph_repository_id=graph_repo.id,
                code_repository_id=repository_id,
                source_file_id=graph_file.id,
                chunk_kind="file",
                path=relative_path,
                line_start=1,
                line_end=max(1, min(len(lines), 200)),
                token_estimate=max(1, len(content) // 4) if content else 0,
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None,
                chunk_metadata={"line_numbered": True, "truncated": len(lines) > 200},
                is_current=True,
            )
        )
    return file_texts


def _read_source_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _line_numbered_slice(lines: list[str], *, start: int, end: int) -> str:
    if not lines:
        return ""
    start = max(1, start)
    end = max(start, min(end, len(lines)))
    return "\n".join(f"{line_no}: {lines[line_no - 1]}" for line_no in range(start, end + 1))
