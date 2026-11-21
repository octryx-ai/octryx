"""SQLite-specific database setup helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

SQLITE_WAL_JOURNAL_SIZE_LIMIT_BYTES = 64 * 1024 * 1024
logger = logging.getLogger(__name__)


def sqlite_database_path(database_url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw_path = database_url[len(prefix) :].strip()
    if not raw_path or raw_path == ":memory:":
        return None
    return Path(raw_path).expanduser().resolve()


def sqlite_sidecar_paths(db_path: Path) -> Mapping[str, Path]:
    return {
        "wal": db_path.with_suffix(db_path.suffix + "-wal"),
        "shm": db_path.with_suffix(db_path.suffix + "-shm"),
        "init_lock": db_path.with_suffix(db_path.suffix + ".init.lock"),
    }


def sqlite_backup_candidates(db_path: Path) -> list[Path]:
    return sorted(db_path.parent.glob(f"{db_path.name}*.bak"))


def acquire_sqlite_file_lock(lock_path: Path):
    import fcntl

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def release_sqlite_file_lock(handle) -> None:
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@asynccontextmanager
async def startup_db_lock(init_lock: asyncio.Lock, *, is_sqlite: bool, database_url: str):
    async with init_lock:
        db_path = sqlite_database_path(database_url) if is_sqlite else None
        if db_path is None:
            yield
            return
        lock_path = db_path.with_suffix(db_path.suffix + ".init.lock")
        handle = await asyncio.to_thread(acquire_sqlite_file_lock, lock_path)
        try:
            yield
        finally:
            await asyncio.to_thread(release_sqlite_file_lock, handle)


async def run_sqlite_startup_maintenance(async_engine: AsyncEngine, *, database_url: str) -> None:
    db_path = sqlite_database_path(database_url)
    if db_path is None:
        return

    async with async_engine.begin() as conn:
        await conn.execute(text(f"PRAGMA journal_size_limit={SQLITE_WAL_JOURNAL_SIZE_LIMIT_BYTES}"))
        # PASSIVE is a bounded best-effort checkpoint. It avoids blocking startup on
        # long-lived readers or sibling processes that still hold SQLite handles.
        checkpoint_result = await conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
        checkpoint_row = checkpoint_result.first()
        if checkpoint_row is None:
            return

        busy = int(checkpoint_row[0] or 0)
        if busy > 0:
            logger.info(
                "SQLite startup checkpoint remained partially busy; continuing without blocking startup",
                extra={
                    "database_path": str(db_path),
                    "busy_readers": busy,
                    "log_frames": int(checkpoint_row[1] or 0),
                    "checkpointed_frames": int(checkpoint_row[2] or 0),
                },
            )
