"""The Evidence operation registry served by PostgreSQL tables keyed by Workspace. The Workspace selects the rows, never
a caller value."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..embedding.catalog import EMBEDDING_SPACES
from ..identity.workspace import WorkspaceId
from ..retrieval.errors import InvalidWorkspaceError
from . import operations as ops
from . import postgres_statements as sql
from .base import EvidenceIndexClient
from .errors import EvidenceIndexContractError, EvidenceIndexUnavailableError
from .operations import OperationKind
from .values import checked_parameters

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 15_000
_WRITE = OperationKind.WRITE


def _project_id(workspace: object) -> str:
    if type(workspace) is not WorkspaceId:
        raise InvalidWorkspaceError()
    return WorkspaceId.parse(workspace).canonical


def _vector_text(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _parsed_vector(value: object) -> list[float] | None:
    if type(value) is not str or not value.startswith("[") or not value.endswith("]"):
        return None
    try:
        return [float(item) for item in value[1:-1].split(",") if item]
    except ValueError:
        return None


class PostgresEvidenceIndexClient(EvidenceIndexClient):
    def __init__(self, session_factory: Callable[[], AsyncSession] | None = None) -> None:
        if session_factory is None:
            # Imported on use: the application database module reads settings at import.
            from ....db.core import async_session_factory

            session_factory = async_session_factory
        self._sessions = session_factory
        self._vectors_present: bool | None = None

    def __repr__(self) -> str:
        return "PostgresEvidenceIndexClient(configured=True)"

    async def aclose(self) -> None:
        pass

    async def run(
        self,
        workspace: WorkspaceId,
        operation_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        project_id = _project_id(workspace)
        try:
            spec = ops.operation(operation_key)
        except KeyError:
            spec = None
        if spec is None:
            raise EvidenceIndexContractError()
        checked = checked_parameters(spec, parameters)
        statement, values = self._statement(operation_key, checked)
        if operation_key in sql.VECTOR_KEYS and not await self.vectors_available():
            # No pgvector on this server: the vector operations do not exist here.
            raise EvidenceIndexContractError()
        values["project_id"] = project_id
        if spec.kind is _WRITE:
            count = await self._execute(statement, values, rows=False)
            return ({"count": count},)
        rows = await self._execute(statement, values, rows=True)
        if operation_key in sql.READ_VECTOR_KEYS:
            return tuple({"vector": _parsed_vector(row.get("vector"))} for row in rows)
        if operation_key in sql.VECTOR_SCOPES:
            return tuple({**row, "distance": float(row["distance"])} for row in rows)
        return rows

    def _statement(self, key: str, checked: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        values = dict(checked)
        if key in sql.LEXICAL:
            return sql.LEXICAL[key], values
        if key in sql.VECTOR_SCOPES:
            space = EMBEDDING_SPACES.get(values.pop("space"))
            if space is None or len(values["vector"]) != space.dimensions:
                raise EvidenceIndexContractError()
            values["vector"] = _vector_text(values["vector"])
            values["space_key"] = space.key
            return sql.vector_search(space.dimensions, sql.VECTOR_SCOPES[key]), values
        if key in sql.SET_VECTOR_KEYS:
            space = EMBEDDING_SPACES[sql.SET_VECTOR_KEYS[key]]
            if len(values["embedding"]) != space.dimensions:
                raise EvidenceIndexContractError()
            values["embedding"] = _vector_text(values["embedding"])
            values["space_key"] = space.key
            return sql.SET_VECTOR, values
        if key in sql.READ_VECTOR_KEYS:
            values["space_key"] = sql.READ_VECTOR_KEYS[key]
            return sql.READ_VECTOR, values
        statements = {
            ops.UPSERT_EVIDENCE_SCOPED: sql.UPSERT_EVIDENCE,
            ops.DELETE_EVIDENCE: sql.DELETE_EVIDENCE,
            ops.MARK_UNMARKED_EVIDENCE: sql.MARK_UNMARKED,
            ops.COUNT_EVIDENCE_BY_KEY: sql.COUNT_EVIDENCE,
        }
        if key not in statements:  # pragma: no cover - every registered key has a statement
            raise EvidenceIndexContractError()
        return statements[key], values

    async def _execute(self, statement: str, values: dict[str, Any], *, rows: bool) -> Any:
        failed = False
        result: Any = None
        try:
            async with self._sessions() as session, session.begin():
                await session.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
                answer = await session.execute(text(statement), values)
                result = tuple(dict(row) for row in answer.mappings().all()) if rows else int(answer.rowcount or 0)
        except SQLAlchemyError as error:
            logger.warning("Evidence index statement failed: error_class=%s", type(error).__name__)
            failed = True
        if failed:
            raise EvidenceIndexUnavailableError()
        return result

    async def vectors_available(self) -> bool:
        if self._vectors_present is None:
            rows = await self._execute(sql.VECTOR_TABLE_PRESENT, {}, rows=True)
            self._vectors_present = bool(rows and rows[0].get("present"))
        return self._vectors_present


def application_index_client() -> PostgresEvidenceIndexClient | None:
    from ....db.core import async_engine

    if async_engine.dialect.name != "postgresql":
        return None
    return PostgresEvidenceIndexClient()


__all__ = ["PostgresEvidenceIndexClient", "application_index_client"]
