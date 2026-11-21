"""Database connector engines: the connection URL, the cached async engine and the resolved configuration."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.services.secret import resolve_secret_refs

from ...models import DatabaseConnector

ENGINE_CACHE: dict[str, AsyncEngine] = {}


def connector_url_from_config(db_type: str, config: dict[str, Any]) -> str:
    direct_dsn = str(config.get("dsn") or "").strip()
    if direct_dsn:
        return direct_dsn
    normalized = str(db_type or "").strip().lower()
    query_options = dict(config.get("query_options") or {})
    if normalized in {"postgres", "postgresql"}:
        return (
            URL.create(
                "postgresql+asyncpg",
                username=str(config.get("username") or ""),
                password=str(config.get("password") or ""),
                host=str(config.get("host") or "localhost"),
                port=int(config.get("port") or 5432),
                database=str(config.get("database") or ""),
                query=query_options,
            )
            .render_as_string(hide_password=False)
        )
    if normalized in {"mysql", "mariadb"}:
        return (
            URL.create(
                "mysql+aiomysql",
                username=str(config.get("username") or ""),
                password=str(config.get("password") or ""),
                host=str(config.get("host") or "localhost"),
                port=int(config.get("port") or 3306),
                database=str(config.get("database") or ""),
                query=query_options,
            )
            .render_as_string(hide_password=False)
        )
    if normalized in {"mssql", "sqlserver"}:
        driver = str(config.get("driver") or query_options.get("driver") or "ODBC Driver 18 for SQL Server")
        return (
            URL.create(
                "mssql+aioodbc",
                username=str(config.get("username") or ""),
                password=str(config.get("password") or ""),
                host=str(config.get("host") or "localhost"),
                port=int(config.get("port") or 1433),
                database=str(config.get("database") or ""),
                query={"driver": driver, **query_options},
            )
            .render_as_string(hide_password=False)
        )
    if normalized == "sqlite":
        file_path = str(config.get("file_path") or config.get("database") or "").strip()
        if not file_path:
            raise HTTPException(status_code=400, detail="SQLite connectors require file_path or database")
        return f"sqlite+aiosqlite:///{file_path}"
    raise HTTPException(status_code=400, detail=f"Unsupported database type: {db_type}")


def engine_connect_args(db_type: str) -> dict[str, Any]:
    if str(db_type or "").strip().lower() == "sqlite":
        return {"timeout": 60}
    return {}


async def get_connector_engine(connector: DatabaseConnector, resolved_config: dict[str, Any]) -> AsyncEngine:
    url = connector_url_from_config(connector.db_type, resolved_config)
    cache_key = f"{connector.id}:{url}"
    engine = ENGINE_CACHE.get(cache_key)
    if engine is None:
        engine = create_async_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args=engine_connect_args(connector.db_type),
        )
        ENGINE_CACHE[cache_key] = engine
    return engine


async def resolve_connector_config(
    db: AsyncSession, *, connector: DatabaseConnector, secret_scope: str
) -> dict[str, Any]:
    config = dict(connector.connection_config or {})
    return await resolve_secret_refs(db, config, tool_name=secret_scope, project_id=connector.project_id)
