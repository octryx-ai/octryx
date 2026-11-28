"""Unresolved reference rows of a persisted code graph run."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CodeGraphFile,
    CodeGraphRepository,
    CodeGraphRun,
    CodeGraphUnresolvedReference,
)
from app.services.code_intelligence.graph_persist_rows import _unresolved_reference_projection

_UnresolvedKeys = set[tuple[str, int | None]]
_ProjectedKeys = set[tuple[str | None, str, str, int | None]]


def _persist_unresolved_rows(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    file_lookup: dict[str, CodeGraphFile],
    unresolved_to_persist: list[Any],
    unresolved_edges: list[tuple[str, int, str, str]],
) -> int:
    scope = {"db": db, "graph_run": graph_run, "graph_repo": graph_repo, "repository_id": repository_id}
    seen_unresolved_keys: _UnresolvedKeys = set()
    seen_projected_unresolved_keys: _ProjectedKeys = set()
    count = _add_reported_unresolved(
        **scope,
        file_lookup=file_lookup,
        items=unresolved_to_persist,
        seen_unresolved_keys=seen_unresolved_keys,
        seen_projected_keys=seen_projected_unresolved_keys,
    )
    count += _add_unresolved_edges(
        **scope,
        file_lookup=file_lookup,
        entries=unresolved_edges,
        seen_unresolved_keys=seen_unresolved_keys,
        seen_projected_keys=seen_projected_unresolved_keys,
    )
    return count


def _add_reported_unresolved(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    file_lookup: dict[str, CodeGraphFile],
    items: list[Any],
    seen_unresolved_keys: _UnresolvedKeys,
    seen_projected_keys: _ProjectedKeys,
) -> int:
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        source_path = str(item.get("source_path") or "").strip()
        symbol_text = str(item.get("symbol_text") or "").strip()
        if not symbol_text:
            continue
        source_file = file_lookup.get(source_path)
        line_start = int(item.get("line") or 0) or None
        unresolved_key = (symbol_text, line_start)
        if unresolved_key in seen_unresolved_keys:
            continue
        seen_unresolved_keys.add(unresolved_key)
        unresolved_ref = CodeGraphUnresolvedReference(
            id=str(uuid4()),
            run_id=graph_run.id,
            graph_repository_id=graph_repo.id,
            source_file_id=source_file.id if source_file else None,
            symbol_text=symbol_text,
            line_start=line_start,
            line_end=line_start,
            reference_context=str(item.get("reference_kind") or ""),
            unresolved_reason=str(item.get("unresolved_reason") or "unresolved_reference"),
        )
        db.add(unresolved_ref)
        projected_key = (
            source_file.id if source_file else None,
            symbol_text,
            str(item.get("reference_kind") or "reference"),
            line_start,
        )
        if projected_key not in seen_projected_keys:
            seen_projected_keys.add(projected_key)
            db.add(_unresolved_reference_projection(graph_run, graph_repo, repository_id, source_file, item))
        count += 1
    return count


def _add_unresolved_edges(
    *,
    db: AsyncSession,
    graph_run: CodeGraphRun,
    graph_repo: CodeGraphRepository,
    repository_id: str,
    file_lookup: dict[str, CodeGraphFile],
    entries: list[tuple[str, int, str, str]],
    seen_unresolved_keys: _UnresolvedKeys,
    seen_projected_keys: _ProjectedKeys,
) -> int:
    count = 0
    for label, line, relation, source in entries:
        source_file = file_lookup.get(source.removeprefix("file:"), None) if source.startswith("file:") else None
        symbol_text = label or relation
        line_start = line or None
        unresolved_key = (symbol_text, line_start)
        if unresolved_key in seen_unresolved_keys:
            continue
        seen_unresolved_keys.add(unresolved_key)
        unresolved_ref = CodeGraphUnresolvedReference(
            id=str(uuid4()),
            run_id=graph_run.id,
            graph_repository_id=graph_repo.id,
            source_file_id=source_file.id if source_file else None,
            symbol_text=symbol_text,
            line_start=line_start,
            line_end=line_start,
            reference_context=source,
            unresolved_reason="symbol_not_found",
        )
        db.add(unresolved_ref)
        projected_key = (source_file.id if source_file else None, symbol_text, relation, line_start)
        if projected_key not in seen_projected_keys:
            seen_projected_keys.add(projected_key)
            projection_item = {
                "symbol_text": symbol_text,
                "reference_kind": relation,
                "line": line,
                "unresolved_reason": "symbol_not_found",
            }
            db.add(_unresolved_reference_projection(graph_run, graph_repo, repository_id, source_file, projection_item))
        count += 1
    return count
