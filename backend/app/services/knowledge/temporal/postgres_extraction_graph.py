"""The node and edge writes of one PostgreSQL graph extraction batch (``postgres_extraction``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_temporal import KnowledgeGraphWorkspace
from ....time_utils import utc_now
from ..embedding.port import EmbeddingPurpose, EmbeddingRuntime
from .errors import GraphStoreError, GraphStoreState
from .postgres_extraction_model import (
    MAX_NAME_CHARS,
    SAME_ENTITY_SIMILARITY,
    BatchResult,
    _vector,
    normalized_fact,
    normalized_name,
)


class _Graph:
    """The writes of one batch inside one Workspace's product group."""

    def __init__(self, db: AsyncSession, project_id: str, group: str, embedding: EmbeddingRuntime, vectors: bool):
        self.db, self.project_id, self.group, self.embedding, self.vectors = db, project_id, group, embedding, vectors
        self._resolved: dict[str, str] = {}

    async def entities(self, names: list[str], result: BatchResult) -> dict[str, str]:
        """``normalized name -> node uuid`` for every name, creating the ones that are new."""
        pending: dict[str, str] = {}
        for name in names:
            key = normalized_name(name)
            if key in self._resolved or key in pending:
                continue
            row = await self._same_name(key)
            if row:
                self._resolved[key] = str(row[0])
            else:
                pending[key] = name.strip()
        if not pending:
            return self._resolved
        keys = list(pending)
        embedded = await self.embedding.embedder.embed([pending[key] for key in keys], EmbeddingPurpose.DOCUMENT)
        now = utc_now()
        for key, vector in zip(keys, embedded, strict=True):
            similar = await self._similar(vector) if self.vectors else None
            if similar:
                self._resolved[key] = str(similar[0])
                continue
            self._resolved[key] = await self._insert_node(pending[key], vector, now)
            result.nodes_created += 1
        return self._resolved

    async def _same_name(self, key: str):
        return (
            await self.db.execute(
                text(
                    "SELECT uuid FROM kg_node WHERE project_id = :p AND group_id = :g "
                    "AND lower(regexp_replace(btrim(name), '\\s+', ' ', 'g')) = :n LIMIT 1"
                ),
                {"p": self.project_id, "g": self.group, "n": key},
            )
        ).first()

    async def _similar(self, vector: list[float]):
        """The nearest existing entity whose name embedding is close enough to count as the same one."""
        return (
            await self.db.execute(
                text(
                    "SELECT uuid FROM kg_node WHERE project_id = :p AND group_id = :g "
                    "AND embedding IS NOT NULL AND vector_dims(embedding) = :d "
                    "AND (embedding <=> CAST(CAST(:v AS text) AS vector)) <= :m "
                    "ORDER BY embedding <=> CAST(CAST(:v AS text) AS vector) LIMIT 1"
                ),
                {
                    "p": self.project_id,
                    "g": self.group,
                    "d": len(vector),
                    "v": _vector(vector),
                    "m": 1.0 - SAME_ENTITY_SIMILARITY,
                },
            )
        ).first()

    async def _insert_node(self, name: str, vector: list[float], now: datetime) -> str:
        node = str(uuid.uuid4())
        values: dict[str, Any] = {
            "p": self.project_id,
            "u": node,
            "n": name[:MAX_NAME_CHARS],
            "g": self.group,
            "c": now,
        }
        columns, params = "project_id, uuid, name, group_id, labels, created_at", ":p, :u, :n, :g, '{Entity}', :c"
        if self.vectors:
            columns += ", embedding"
            params += ", CAST(CAST(:v AS text) AS vector)"
            values["v"] = _vector(vector)
        await self.db.execute(text(f"INSERT INTO kg_node ({columns}) VALUES ({params})"), values)  # noqa: S608
        return node

    async def fact(
        self,
        source: str,
        relation: str,
        target: str,
        fact: str,
        episode: str,
        valid_at: datetime,
        vector: list[float] | None,
        result: BatchResult,
    ) -> None:
        same = (
            await self.db.execute(
                text(
                    "SELECT uuid, episodes FROM kg_edge WHERE project_id = :p AND group_id = :g AND source_uuid = :s "
                    "AND target_uuid = :t AND relation = :r "
                    "AND lower(regexp_replace(btrim(fact), '\\s+', ' ', 'g')) = :f "
                    "LIMIT 1"
                ),
                {
                    "p": self.project_id,
                    "g": self.group,
                    "s": source,
                    "t": target,
                    "r": relation,
                    "f": normalized_fact(fact),
                },
            )
        ).first()
        if same:
            if episode not in (same[1] or []):
                await self.db.execute(
                    text(
                        "UPDATE kg_edge SET episodes = array_append(episodes, :e) WHERE project_id = :p AND uuid = :u"
                    ),
                    {"e": episode, "p": self.project_id, "u": same[0]},
                )
            result.edges_merged += 1
            return
        values: dict[str, Any] = {
            "p": self.project_id,
            "u": str(uuid.uuid4()),
            "r": relation,
            "f": fact,
            "e": [episode],
            "g": self.group,
            "s": source,
            "t": target,
            "c": utc_now(),
            "va": valid_at,
        }
        columns = "project_id, uuid, relation, fact, episodes, group_id, source_uuid, target_uuid, created_at, valid_at"
        params = ":p, :u, :r, :f, CAST(:e AS text[]), :g, :s, :t, :c, :va"
        if self.vectors and vector is not None:
            columns += ", embedding"
            params += ", CAST(CAST(:v AS text) AS vector)"
            values["v"] = _vector(vector)
        await self.db.execute(text(f"INSERT INTO kg_edge ({columns}) VALUES ({params})"), values)  # noqa: S608
        result.edges_created += 1


async def vectors_available(db: AsyncSession) -> bool:
    row = await db.execute(
        text("SELECT 1 FROM information_schema.columns WHERE table_name = 'kg_edge' AND column_name = 'embedding'")
    )
    return row.first() is not None


async def ensure_workspace_graph(db: AsyncSession, project_id: str, space_key: str) -> None:
    row = await db.get(KnowledgeGraphWorkspace, project_id)
    if row is None:
        db.add(KnowledgeGraphWorkspace(project_id=project_id, embedding_space_key=space_key))
        await db.flush()
    elif row.embedding_space_key != space_key:
        # The graph's vectors belong to another space; ranking them with this one would be wrong.
        raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION)
