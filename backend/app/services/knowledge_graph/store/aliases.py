"""Alias normalization, lookup and registration for graph nodes."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import KnowledgeGraphAlias, KnowledgeGraphNode

_WS = re.compile(r"\s+")


def normalize_alias(value: Any) -> str:
    return _WS.sub(" ", str(value or "").strip().lower())


def _project_scope(project_id: str | None) -> str:
    return project_id or ""


def _project_filter(column, project_id: str | None):
    return column.is_(None) if project_id is None else column == project_id


async def _node_aliases(db: AsyncSession, node_id: str) -> list[KnowledgeGraphAlias]:
    return list(
        (await db.execute(select(KnowledgeGraphAlias).where(KnowledgeGraphAlias.node_id == node_id)))
        .scalars()
        .all()
    )


async def resolve_node_by_alias(
    db: AsyncSession, *, project_id: str | None, alias: str
) -> KnowledgeGraphNode | None:
    norm = normalize_alias(alias)
    if not norm:
        return None
    row = (
        await db.execute(
            select(KnowledgeGraphAlias).where(
                KnowledgeGraphAlias.project_scope == _project_scope(project_id),
                KnowledgeGraphAlias.normalized_alias == norm,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return await db.get(KnowledgeGraphNode, row.node_id)


async def _ensure_aliases(
    db: AsyncSession, node: KnowledgeGraphNode, scope: str, values: list[Any], alias_type: str = "name"
) -> None:
    existing = {alias.normalized_alias for alias in await _node_aliases(db, node.id)}
    for value in values:
        norm = normalize_alias(value)
        if not norm or norm in existing:
            continue
        conflict = (
            await db.execute(
                select(KnowledgeGraphAlias).where(
                    KnowledgeGraphAlias.project_scope == scope,
                    KnowledgeGraphAlias.normalized_alias == norm,
                )
            )
        ).scalar_one_or_none()
        if conflict is not None and conflict.node_id != node.id:
            # Alias already resolves to a different node; do not steal it.
            continue
        db.add(
            KnowledgeGraphAlias(
                id=str(uuid.uuid4()),
                node_id=node.id,
                project_scope=scope,
                alias_type=alias_type,
                alias_value=str(value).strip(),
                normalized_alias=norm,
            )
        )
        existing.add(norm)
    await db.flush()
