"""Database startup helpers that separate schema bootstrap from app runtime startup."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeAlias

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core import async_engine, init_db, settings
from .sqlite import run_sqlite_startup_maintenance

DatabaseSeeder: TypeAlias = Callable[[AsyncSession], Awaitable[None]]

# Serializes schema bootstrap and seeding across processes (several API processes and the platform
# worker start together). The seeders check-then-insert; two processes on a database
# that lacks a seeded row would both insert it. Any fixed 64-bit value; "octrystr" in ASCII.
STARTUP_ADVISORY_LOCK_KEY = 0x6F63747279737472


@asynccontextmanager
async def cross_process_startup_lock(engine: Any = None) -> AsyncIterator[None]:
    engine = engine or async_engine
    if engine.dialect.name != "postgresql":
        yield
        return
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": STARTUP_ADVISORY_LOCK_KEY})
            yield


async def ensure_database_schema_ready() -> None:
    await init_db()


async def ensure_runtime_database_ready(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    seed_database: DatabaseSeeder | None = None,
) -> None:
    async with cross_process_startup_lock():
        await ensure_database_schema_ready()
        if seed_database is not None:
            async with session_factory() as db:
                await seed_database(db)
    await run_sqlite_startup_maintenance(async_engine, database_url=settings.database_url)
