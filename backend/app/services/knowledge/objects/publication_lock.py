"""The cross-process serialization boundary of one object's publication. A committed reference never names deleted
bytes; other engines report ``serialized=False``."""

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
    # A defect signal, never a request state, so it carries no value.
    def __init__(self) -> None:
        super().__init__("object publication lock requires a workspace id and an object key")


@dataclass(frozen=True, slots=True)
class PublicationLock:
    # ``serialized`` False (no advisory locks) is a fact the caller must surface, not a success.
    project_id: str
    object_key: str
    lock_key: int
    serialized: bool


def publication_lock_key(project_id: object, object_key: object) -> int:
    # Deterministic, not collision-free: a collision only serializes two objects (see ``advisory_locks.py``).
    if type(project_id) is not str or type(object_key) is not str or not project_id or not object_key:
        raise ObjectPublicationLockError()
    return advisory_lock_key(LOCK_NAMESPACE, project_id, object_key)


def serializes_object_publication(db: AsyncSession) -> bool:
    if type(db) is not AsyncSession:
        raise ObjectPublicationLockError()
    return serializes_advisory_locks(db)


async def lock_object_publication(
    db: AsyncSession, *, project_id: str, object_key: str
) -> PublicationLock:
    # Nothing to release: the transaction's commit or rollback, also after a crash, releases the lock.
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

