"""Lifecycle helpers for native Code Graph persistence."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CodeGraphChunk,
    CodeGraphEdge,
    CodeGraphFile,
    CodeGraphNode,
    CodeGraphReference,
    CodeGraphRoute,
    CodeGraphSymbol,
)


async def mark_previous_graph_rows_stale(*, db: AsyncSession, graph_repo_id: str) -> None:
    await db.execute(
        update(CodeGraphFile)
        .where(CodeGraphFile.graph_repository_id == graph_repo_id, CodeGraphFile.is_current.is_(True))
        .values(is_current=False, is_stale=True)
    )
    await db.execute(
        update(CodeGraphNode)
        .where(CodeGraphNode.graph_repository_id == graph_repo_id, CodeGraphNode.is_current.is_(True))
        .values(is_current=False, is_stale=True)
    )
    await db.execute(
        update(CodeGraphSymbol)
        .where(CodeGraphSymbol.graph_repository_id == graph_repo_id, CodeGraphSymbol.is_current.is_(True))
        .values(is_current=False)
    )
    for model in (CodeGraphEdge, CodeGraphReference, CodeGraphRoute, CodeGraphChunk):
        await db.execute(
            update(model)
            .where(model.graph_repository_id == graph_repo_id, model.is_current.is_(True))
            .values(is_current=False)
        )


__all__ = ["mark_previous_graph_rows_stale"]
