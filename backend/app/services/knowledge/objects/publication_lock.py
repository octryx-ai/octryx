"""The cross-process serialization boundary of one object's publication.

The ingestion boundary writes the immutable content-addressed object **before** it
commits the revision that references it. "This object has no governed reference" is
therefore only true at the moment it is measured, and one interleaving is genuinely
destructive: an operator retention pass measures "unreferenced", deletes the bytes, and an
ingestion that had already written (or found) exactly those bytes commits a reference to
them afterwards. The ledger then points at an object that is gone.

Two things that mutually exclude each other must be serialized, and they run in **different
processes** on **different database sessions** — the API/worker process that ingests, and the
operator process that reconciles. Neither a row this code reads nor a window this code waits
out can do that: a read only reports the committed past, and a window is a timing assumption.
PostgreSQL's transaction-scoped advisory lock can, because it is held by the *transaction*
and released by the database when that transaction ends, however it ends:

- the ingestion takes it before it writes the object and holds it until the revision is
  committed (or rolled back), so its whole write-then-publish sequence is one critical
  section;
- the retention pass takes it before it re-verifies the ledger and holds it until the
  deletion and its audit row are committed, so its verify-then-delete sequence is one
  critical section too.

Whichever of the two arrives second waits inside the database. If the ingestion wins, the
pass re-reads the ledger *after* the reference is committed and skips the key. If the pass
wins, the ingestion's write happens after the object was removed, so it re-creates the bytes
at the same content address and its reference is valid. There is no interleaving left in
which a committed reference names deleted bytes, and no interval anyone has to guess right.

The lock key is derived, never stored: one 64-bit key per ``(namespace, project_id,
object_key)``, from a SHA-256 over the three NUL-separated parts (see
``advisory_locks.py``), so the boundary needs no table, no migration and no cleanup. The
derivation is *deterministic*, which is the only property the boundary needs: the two sides of
one object always compute the same key. It is not collision-free — 64 bits truncated from a
digest can collide — and it does not have to be: a collision makes two unrelated objects
serialize against each other, which is extra, conservative waiting, never a boundary that
fails to hold. :data:`LOCK_NAMESPACE` is part of the digest and versioned, so an unrelated
future advisory-lock user of this database is separated by construction.

Engine dependency, stated rather than hidden: advisory locks are a PostgreSQL facility, and
PostgreSQL is the product's transactional database. On any other engine (the SQLite test
harness) :func:`lock_object_publication` takes no lock and says so — it returns
``serialized=False`` and logs it, so "the boundary was held" stays a recorded fact rather than an
assumption. Nothing here
retains a statement, a driver error or a key: the only value that leaves this module is an
integer this module derived.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..ledger.advisory_locks import advisory_lock_key, serializes_advisory_locks, take_transaction_lock

logger = logging.getLogger(__name__)

# Versioned, so this slice's advisory keys are separated from another future user of
# PostgreSQL's single advisory-lock space in the same database.
LOCK_NAMESPACE = "octryx.knowledge.object.publication.v1"


class ObjectPublicationLockError(Exception):
    """A caller passed something other than a Workspace id and a derived object key.

    Both call sites pass values they derived themselves (the authorized Workspace's project
    id and the object boundary's own key derivation), so this is a defect signal, never a
    request state, and it carries no value.
    """

    def __init__(self) -> None:
        super().__init__("object publication lock requires a workspace id and an object key")


@dataclass(frozen=True, slots=True)
class PublicationLock:
    """What one lock attempt established.

    ``serialized`` is True only when a transaction-scoped lock is really held for the
    remainder of the caller's transaction. It is False on an engine without advisory locks,
    which is a recorded fact the caller must be able to surface — not a success.
    """

    project_id: str
    object_key: str
    lock_key: int
    serialized: bool


def publication_lock_key(project_id: object, object_key: object) -> int:
    """The deterministic 64-bit advisory key of one Workspace's one object.

    A SHA-256 over the namespace, the Workspace id and the object key, NUL-separated so no
    concatenation of two shorter values can produce another pair's digest input, truncated to
    the signed 64-bit argument ``pg_advisory_xact_lock`` takes. Deterministic, not
    collision-free: see ``advisory_locks.py`` for why the boundary only needs the former.
    """
    if type(project_id) is not str or type(object_key) is not str or not project_id or not object_key:
        raise ObjectPublicationLockError()
    return advisory_lock_key(LOCK_NAMESPACE, project_id, object_key)


def serializes_object_publication(db: AsyncSession) -> bool:
    """True when this session's engine can hold the publication boundary."""
    if type(db) is not AsyncSession:
        raise ObjectPublicationLockError()
    return serializes_advisory_locks(db)


async def lock_object_publication(
    db: AsyncSession, *, project_id: str, object_key: str
) -> PublicationLock:
    """Hold this object's publication boundary for the rest of ``db``'s transaction.

    Blocks inside the database while another transaction — in this process or any other —
    holds the same key. Returns as soon as the lock is granted; there is nothing to release,
    because the transaction's commit or rollback releases it, including the rollback a
    crashed process's connection produces.
    """
    lock_key = publication_lock_key(project_id, object_key)
    if not serializes_object_publication(db):
        # Recorded, not silent: the caller surfaces this as part of its outcome.
        logger.warning(
            "Knowledge object publication is not serialized on this engine: workspace=%s", project_id
        )
        return PublicationLock(
            project_id=project_id, object_key=object_key, lock_key=lock_key, serialized=False
        )
    await take_transaction_lock(db, lock_key)
    return PublicationLock(
        project_id=project_id, object_key=object_key, lock_key=lock_key, serialized=True
    )

