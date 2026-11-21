"""The one derivation and one statement behind the Knowledge PostgreSQL advisory locks.

Two Knowledge boundaries need *cross-process* mutual exclusion that no row and
no waiting interval can give: one object's publication against its deletion
(``object_publication_lock.py``) and one Workspace's governance transitions against an
in-flight deletion (``services/knowledge_retention/governance_lock.py``). Both are
PostgreSQL transaction-scoped advisory locks, so both derive a 64-bit key the same way and
issue the same statement. That lives here once, because two copies of a truncation rule are
two chances to truncate differently.

**What a derived key must guarantee, and what it must not be claimed to guarantee.** The lock
is only ever used to *acquire* mutual exclusion, so correctness needs exactly one property:
equal inputs must always derive the equal key. That is what a SHA-256 over the NUL-separated
parts gives deterministically. Distinctness is *not* guaranteed and is not needed: 64 bits
truncated from a digest can collide, and by the birthday bound a collision becomes likely only
around 2**32 distinct keys. A collision has one effect — two unrelated objects (or a
Workspace's governance and some other key) would serialize against each other, i.e. one waits
where it did not have to. That is conservative: extra blocking, never a boundary that fails to
hold. The namespace string is part of the digest and is versioned, so an unrelated future user
of this database's single advisory-lock space is separated by construction rather than by luck.

Nothing here retains a statement, a driver error or an input: the only value it produces is an
integer it derived itself.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

POSTGRESQL = "postgresql"

# One 64-bit argument, taken and released by the transaction. Never ``pg_advisory_lock``: a
# session-scoped lock would outlive the transaction on a pooled connection.
_LOCK_STATEMENT = text("SELECT pg_advisory_xact_lock(:lock_key)")


def advisory_lock_key(namespace: str, *parts: str) -> int:
    """The deterministic signed 64-bit advisory key of one namespace and its parts.

    Callers validate their own parts and raise their own contract error; this function assumes
    non-empty strings. The parts are NUL-separated, so no concatenation of two shorter values
    can produce another tuple's digest input.
    """
    digest = hashlib.sha256(
        b"\x00".join(part.encode("utf-8") for part in (namespace, *parts))
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def dialect_name(db: AsyncSession) -> str:
    """The dialect of whatever this session is bound to, or an empty name.

    Never raises and never returns a driver object: an engine this code cannot recognise is
    the same as an engine without advisory locks.
    """
    bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", None)
    return name if type(name) is str else ""


def serializes_advisory_locks(db: AsyncSession) -> bool:
    """True when this session's engine can hold a transaction-scoped advisory lock."""
    return dialect_name(db) == POSTGRESQL


async def take_transaction_lock(db: AsyncSession, lock_key: int) -> None:
    """Hold ``lock_key`` for the rest of ``db``'s transaction, waiting inside the database.

    There is nothing to release: the transaction's commit or rollback releases it, including
    the rollback a crashed process's connection produces.
    """
    await db.execute(_LOCK_STATEMENT, {"lock_key": lock_key})
