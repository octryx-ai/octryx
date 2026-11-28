"""The one derivation and one statement behind the Knowledge PostgreSQL advisory locks. Equal inputs derive equal keys;
a collision only adds waiting."""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

POSTGRESQL = "postgresql"

# Transaction-scoped: a session lock (``pg_advisory_lock``) would outlive the transaction on a pooled connection.
_LOCK_STATEMENT = text("SELECT pg_advisory_xact_lock(:lock_key)")


def advisory_lock_key(namespace: str, *parts: str) -> int:
    # NUL-separated, so no concatenation of two shorter values yields another tuple's digest input.
    digest = hashlib.sha256(
        b"\x00".join(part.encode("utf-8") for part in (namespace, *parts))
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def dialect_name(db: AsyncSession) -> str:
    bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", None)
    return name if type(name) is str else ""


def serializes_advisory_locks(db: AsyncSession) -> bool:
    return dialect_name(db) == POSTGRESQL


async def take_transaction_lock(db: AsyncSession, lock_key: int) -> None:
    # Nothing to release: the transaction's commit or rollback, also a crashed connection's, releases the lock.
    await db.execute(_LOCK_STATEMENT, {"lock_key": lock_key})
