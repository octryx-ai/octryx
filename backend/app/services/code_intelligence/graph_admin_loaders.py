"""Database loaders behind the code graph admin health snapshot."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CodeGraphChunk,
    CodeGraphFile,
    CodeGraphReference,
    CodeGraphRepository,
    CodeGraphRoute,
    CodeGraphRun,
    CodeGraphStaleness,
    CodeGraphSymbol,
    CodeRepository,
)
from app.services.code_intelligence.graph_sync import load_graph_staleness_warnings
from app.services.code_intelligence.storage_runtime import _normalize_path


async def _latest_run(db: AsyncSession, graph_repo: CodeGraphRepository) -> CodeGraphRun | None:
    if graph_repo.latest_run_id:
        run = await db.get(CodeGraphRun, graph_repo.latest_run_id)
        if run is not None:
            return run
    return (
        await db.execute(
            select(CodeGraphRun)
            .where(CodeGraphRun.graph_repository_id == graph_repo.id)
            .order_by(CodeGraphRun.started_at.desc())
        )
    ).scalar_one_or_none()


async def _load_run_history(
    db: AsyncSession,
    *,
    graph_repo: CodeGraphRepository,
    limit: int,
) -> list[CodeGraphRun]:
    return list(
        (
            await db.execute(
                select(CodeGraphRun)
                .where(CodeGraphRun.graph_repository_id == graph_repo.id)
                .order_by(CodeGraphRun.started_at.desc())
                .limit(max(1, min(int(limit or 5), 20)))
            )
        )
        .scalars()
        .all()
    )


async def _load_sync_state(db: AsyncSession, *, repo: CodeRepository) -> dict[str, Any]:
    repo_root = _normalize_path(repo.repo_root)
    if not repo_root.exists() or not repo_root.is_dir():
        return {"state": "unknown", "warnings": [], "summary": {"error": "repository_root_unavailable"}}
    return await load_graph_staleness_warnings(db=db, repository_id=repo.id, repo_root=repo_root)


async def _load_graph_summary(db: AsyncSession, *, run: CodeGraphRun) -> dict[str, Any]:
    languages = {
        str(language or "unknown"): int(count or 0)
        for language, count in (
            await db.execute(
                select(CodeGraphFile.language, func.count(CodeGraphFile.id))
                .where(CodeGraphFile.run_id == run.id, CodeGraphFile.is_current.is_(True))
                .group_by(CodeGraphFile.language)
            )
        ).all()
    }
    return {
        "file_count": run.file_count,
        "node_count": run.node_count,
        "edge_count": run.edge_count,
        "symbol_count": await _count(db, CodeGraphSymbol, run.id),
        "reference_count": await _count(db, CodeGraphReference, run.id),
        "route_count": await _count(db, CodeGraphRoute, run.id),
        "chunk_count": await _count(db, CodeGraphChunk, run.id),
        "unresolved_reference_count": run.unresolved_reference_count,
        "language_distribution": languages,
    }


async def _count(db: AsyncSession, model: Any, run_id: str) -> int:
    return int((await db.execute(select(func.count(model.id)).where(model.run_id == run_id))).scalar() or 0)


async def _load_stale_files(
    db: AsyncSession,
    *,
    graph_repo: CodeGraphRepository,
    sync_state: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_items = max(1, min(int(limit or 10), 50))
    for warning in list(sync_state.get("warnings") or [])[:max_items]:
        path = str(warning.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        entries.append(
            {
                "file_path": path,
                "status": warning.get("status") or "stale",
                "reason": warning.get("message") or "",
                "source": "workspace",
                "checked_at": None,
            }
        )
    if len(entries) >= max_items:
        return entries
    rows = (
        await db.execute(
            select(CodeGraphStaleness)
            .where(CodeGraphStaleness.graph_repository_id == graph_repo.id, CodeGraphStaleness.status != "fresh")
            .order_by(CodeGraphStaleness.checked_at.desc())
            .limit(max_items)
        )
    ).scalars()
    for row in rows:
        if row.file_path in seen:
            continue
        entries.append(
            {
                "file_path": row.file_path,
                "status": row.status,
                "reason": row.reason or "",
                "source": "persisted",
                "checked_at": row.checked_at.isoformat() if row.checked_at else None,
            }
        )
        if len(entries) >= max_items:
            break
    return entries


async def _load_parse_errors(db: AsyncSession, *, run: CodeGraphRun, limit: int) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(CodeGraphFile)
            .where(
                CodeGraphFile.run_id == run.id,
                CodeGraphFile.parse_error.is_not(None),
                CodeGraphFile.parse_error != "",
            )
            .order_by(CodeGraphFile.file_path.asc())
            .limit(max(1, min(int(limit or 10), 50)))
        )
    ).scalars()
    return [
        {
            "file_path": row.file_path,
            "language": row.language,
            "parse_error": row.parse_error,
            "is_current": bool(row.is_current),
        }
        for row in rows
    ]
