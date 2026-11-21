"""The Workspace temporal knowledge graph read from PostgreSQL (graph on Postgres, part B).

The product reads the graph through a handful of fixed, one-hop Cypher statements
(``changes._FACTS``/``_FACTS_OF_KINDS``, ``fact_expansion._DIRECT``/``_HOP``,
``visualization_queries.FACTS_QUERY``) and through the ranked edge search of
``changes.ranked_edge_uuids``. :class:`PostgresGraphDriver` answers exactly those statements
from ``kg_node``/``kg_edge`` with the same record shape, so the read paths keep their contracts.
Any other statement is refused as a contract violation; nothing here interprets Cypher.

Every statement is scoped by the driver's Workspace (``project_id``), never by a caller value.
Failures are :class:`GraphStoreError` with a fixed state and no driver text.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import GraphStoreError, GraphStoreState

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 8_000
MIN_SIMILARITY = 0.3
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

_SELECT = (
    "SELECT e.uuid AS uuid, e.relation AS relation, e.fact AS fact, e.episodes AS episodes, "
    "e.created_at AS created_at, a.name AS source, b.name AS target, "
    "a.uuid AS source_uuid, b.uuid AS target_uuid "
    "FROM kg_edge AS e "
    "JOIN kg_node AS a ON a.project_id = e.project_id AND a.uuid = e.source_uuid "
    "JOIN kg_node AS b ON b.project_id = e.project_id AND b.uuid = e.target_uuid "
    "WHERE e.project_id = :project_id"
)
_GROUP = " AND e.group_id = :group"
_EPISODES = " AND e.episodes && CAST(:episodes AS text[])"
_ORDER = " ORDER BY e.uuid LIMIT :limit"

SQL_FACTS = _SELECT + _GROUP + _EPISODES + _ORDER
SQL_FACTS_OF_KINDS = _SELECT + _GROUP + _EPISODES + " AND e.relation = ANY(CAST(:kinds AS text[]))" + _ORDER
SQL_HOP = (
    _SELECT
    + _GROUP
    + " AND (a.uuid = ANY(CAST(:entities AS text[])) OR b.uuid = ANY(CAST(:entities AS text[])))"
    + _ORDER
)
SQL_EXPLORER = (
    _SELECT
    + _EPISODES
    + " AND (:focus = '' OR a.uuid = :focus OR b.uuid = :focus)"
    + " AND (:query = '' OR position(:query IN lower(a.name)) > 0 OR position(:query IN lower(b.name)) > 0"
    + " OR position(:query IN lower(e.fact)) > 0)"
    + _ORDER
)
SQL_FULLTEXT = (
    "SELECT e.uuid AS uuid FROM kg_edge AS e, to_tsquery('simple', :terms) AS q "
    "WHERE e.project_id = :project_id AND e.group_id = :group AND e.fact_tsv @@ q "
    "ORDER BY ts_rank_cd(e.fact_tsv, q) DESC, e.uuid LIMIT :limit"
)
SQL_SIMILAR = (
    "SELECT uuid FROM (SELECT e.uuid AS uuid, "
    "(e.embedding <=> CAST(CAST(:vector AS text) AS vector)) AS distance FROM kg_edge AS e "
    "WHERE e.project_id = :project_id AND e.group_id = :group AND e.embedding IS NOT NULL "
    "AND vector_dims(e.embedding) = :dimensions) AS ranked "
    "WHERE distance <= :max_distance ORDER BY distance, uuid LIMIT :limit"
)


def _statements() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Cypher statement -> (SQL, the parameter names it takes). Imported on use: no cycles."""
    from .changes import _FACTS, _FACTS_OF_KINDS
    from .fact_expansion import _DIRECT, _HOP
    from .visualization_queries import FACTS_QUERY

    return {
        _FACTS: (SQL_FACTS, ("group", "episodes", "limit")),
        _FACTS_OF_KINDS: (SQL_FACTS_OF_KINDS, ("group", "episodes", "kinds", "limit")),
        _DIRECT: (SQL_FACTS, ("group", "episodes", "limit")),
        _HOP: (SQL_HOP, ("group", "entities", "limit")),
        FACTS_QUERY: (SQL_EXPLORER, ("episodes", "query", "focus", "limit")),
    }


def _plain(value: Any) -> Any:
    # Timestamps are answered as text, the shape the graph readers expect.
    return str(value) if isinstance(value, datetime) else value


def _vector_text(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


class PostgresGraphDriver:
    """Read-only graph access for one Workspace, shaped like the Graphiti driver's ``execute_query``."""

    def __init__(self, project_id: str, session_factory: Callable[[], AsyncSession] | None = None) -> None:
        if session_factory is None:
            from ....db.core import async_session_factory

            session_factory = async_session_factory
        self._project_id = project_id
        self._sessions = session_factory

    def __repr__(self) -> str:
        return "PostgresGraphDriver(configured=True)"

    async def close(self) -> None:
        """Nothing to release: sessions are per call."""

    async def execute_query(self, statement: str, **parameters: Any) -> tuple[list[dict[str, Any]], None, None]:
        known = _statements().get(statement)
        if known is None or set(parameters) != set(known[1]):
            raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION)
        sql, _ = known
        values = {"project_id": self._project_id, **parameters}
        if "episodes" in values:
            values["episodes"] = [str(item) for item in values["episodes"]]
        rows = await self._rows(sql, values)
        return [{key: _plain(value) for key, value in row.items()} for row in rows], None, None

    async def ranked_edges(self, query: str, group: str, vector: list[float] | None, limit: int) -> list[list[str]]:
        """Full-text and semantic edge rankings inside ``group``, as two uuid lists."""
        words = sorted({word.casefold() for word in _WORD.findall(query)})[:32]
        lexical: list[str] = []
        if words:
            terms = " | ".join(words)
            rows = await self._rows(
                SQL_FULLTEXT, {"project_id": self._project_id, "group": group, "terms": terms, "limit": limit}
            )
            lexical = [str(row["uuid"]) for row in rows]
        semantic: list[str] = []
        if vector:
            rows = await self._rows(
                SQL_SIMILAR,
                {
                    "project_id": self._project_id,
                    "group": group,
                    "vector": _vector_text(vector),
                    "dimensions": len(vector),
                    "max_distance": 1.0 - MIN_SIMILARITY,
                    "limit": limit,
                },
            )
            semantic = [str(row["uuid"]) for row in rows]
        return [lexical, semantic]

    async def _rows(self, sql: str, values: dict[str, Any]) -> list[dict[str, Any]]:
        failed = False
        rows: list[dict[str, Any]] = []
        try:
            async with self._sessions() as session, session.begin():
                await session.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
                rows = [dict(row) for row in (await session.execute(text(sql), values)).mappings().all()]
        except SQLAlchemyError as error:
            logger.warning("Knowledge graph read failed: error_class=%s", type(error).__name__)
            failed = True
        if failed:
            raise GraphStoreError(GraphStoreState.UNAVAILABLE)
        return rows


__all__ = ["PostgresGraphDriver"]
