"""Canonical database runtime module."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import DateTime, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session

from ..config import get_settings
from ..services.observability import agent_metrics
from ..services.request_context import get_current_request_id, get_current_rls_user_id
from .sqlite import SQLITE_WAL_JOURNAL_SIZE_LIMIT_BYTES, startup_db_lock

settings = get_settings()
_INIT_DB_LOCK = asyncio.Lock()
logger = logging.getLogger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")

async_engine = create_async_engine(
    settings.database_url,
    echo=False,  # SQL query logging is too noisy; use sqlalchemy.engine logger level if needed
    future=True,
    connect_args={"timeout": 60} if _is_sqlite else {},
    # A Postgres restart leaves dead pooled connections; check each on checkout instead of failing the request.
    pool_pre_ping=not _is_sqlite,
    **({} if _is_sqlite else {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow,
                              "pool_timeout": settings.db_pool_timeout}),
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def _coerce_aware_datetime_to_naive_utc(value: object) -> object:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _normalize_naive_datetime_columns(instance: object) -> None:
    mapper = getattr(instance, "__mapper__", None)
    if mapper is None:
        return
    for column_attr in mapper.column_attrs:
        columns = getattr(column_attr, "columns", ())
        if len(columns) != 1:
            continue
        column = columns[0]
        if not isinstance(column.type, DateTime) or column.type.timezone:
            continue
        current_value = getattr(instance, column_attr.key, None)
        normalized_value = _coerce_aware_datetime_to_naive_utc(current_value)
        if normalized_value is not current_value:
            setattr(instance, column_attr.key, normalized_value)


agent_metrics.install()  # counts committed agent rows for /metrics (services/observability/agent_metrics.py)


@event.listens_for(Session, "before_flush")
def _normalize_session_datetimes(session, _flush_context, _instances):
    for instance in set(session.new).union(session.dirty):
        _normalize_naive_datetime_columns(instance)


if _is_sqlite:

    @event.listens_for(async_engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute(f"PRAGMA journal_size_limit={SQLITE_WAL_JOURNAL_SIZE_LIMIT_BYTES}")
        cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            rls_user_id = get_current_rls_user_id()
            if rls_user_id and not _is_sqlite:
                try:
                    await session.execute(
                        text("SELECT set_config('app.current_user_id', :uid, true)"),
                        {"uid": rls_user_id},
                    )
                except Exception:
                    logger.exception(
                        "Failed to establish RLS session context (request_id=%s)",
                        get_current_request_id(),
                    )
                    raise RuntimeError("Failed to establish request data isolation")
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Fill gaps only: the schema comes from ``alembic upgrade head``, which every deployment runs before the API
    (Kubernetes: the migrate init container; octryx-docker: service ``migrate``). ``create_all`` before an upgrade is
    not supported: a revision does not adopt a table ``create_all`` built."""
    async with startup_db_lock(_INIT_DB_LOCK, is_sqlite=_is_sqlite, database_url=settings.database_url):
        from .. import models as _models  # noqa: F401

        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_create_missing_indexes)


def _create_missing_indexes(sync_conn) -> None:
    # Collect names of indexes already present in the database.
    existing_indexes = set()
    if _is_sqlite:
        result = sync_conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
    else:
        result = sync_conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
    for row in result.fetchall():
        existing_indexes.add(row[0])
    for table in Base.metadata.sorted_tables:
        # Use actual DB columns to avoid attempting to create
        # indexes on columns the database does not have.
        if _is_sqlite:
            pragma_rows = sync_conn.execute(text(f"PRAGMA table_info({table.name})")).fetchall()
            actual_col_names = {row[1] for row in pragma_rows}
        else:
            col_rows = sync_conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :tbl"
            ), {"tbl": table.name}).fetchall()
            actual_col_names = {row[0] for row in col_rows}
        preparer = sync_conn.dialect.identifier_preparer
        for index in table.indexes:
            # The DDL emitter truncates names beyond max_identifier_length
            # (63 on PostgreSQL) to a hash-suffixed form; compare against
            # that rendered name too, or the index looks missing forever.
            rendered_name = preparer.format_index(index).strip('"')
            if index.name in existing_indexes or rendered_name in existing_indexes:
                continue
            if not {c.name for c in index.columns}.issubset(actual_col_names):
                continue
            index.create(bind=sync_conn, checkfirst=False)
