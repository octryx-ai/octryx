"""SQLite's one writer: a write that met another one's lock (retried by its owner)."""

from __future__ import annotations


def is_sqlite_lock_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


__all__ = ["is_sqlite_lock_error"]
