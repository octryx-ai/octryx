"""Which embedding spaces a Workspace database carries vectors for.

The embedding step records a space once its property and index exist; vector retrieval checks the
record, so a Workspace without vectors gets an explicit state instead of a query on a missing index.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeWorkspaceVectorSpace


async def vector_space_ready(db: AsyncSession, project_id: str, space_key: str) -> bool:
    row = await db.execute(
        select(KnowledgeWorkspaceVectorSpace.space_key).where(
            KnowledgeWorkspaceVectorSpace.project_id == project_id,
            KnowledgeWorkspaceVectorSpace.space_key == space_key,
        )
    )
    return row.scalar_one_or_none() is not None


async def record_vector_space(db: AsyncSession, project_id: str, space_key: str) -> None:
    """Record the space inside the caller's transaction; a concurrent record is the same fact."""
    if await vector_space_ready(db, project_id, space_key):
        return
    try:
        async with db.begin_nested():
            db.add(KnowledgeWorkspaceVectorSpace(project_id=project_id, space_key=space_key))
    except IntegrityError:
        pass


__all__ = ["record_vector_space", "vector_space_ready"]
