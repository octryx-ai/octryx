"""Write an accepted upload's bytes under the publication boundary.

Shared by text-native and sandboxed ingestion, so both keep the same order: the Workspace's
ownership row, then the content address derived without a request, then the transaction-scoped
advisory lock on ``(Workspace, object key)``, then the retention-hold check, and only then the
write. The caller registers the revision in the same transaction, which is what makes the write
and the reference one critical section a retention pass cannot interleave with
(``text_ingest.py`` explains the cost).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..ledger.errors import (
    EvidenceLedgerContractError,
    EvidencePayloadTooLargeError,
    EvidenceStoreNotConfiguredError,
    EvidenceStoreUnavailableError,
)
from ..objects import (
    KnowledgeObjectError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectTooLargeError,
    StoredObject,
)
from ..objects.publication_lock import lock_object_publication
from ..retention.holds import object_key_is_held
from ..runtime import EvidenceRuntime

logger = logging.getLogger(__name__)


async def publish_object(
    db: AsyncSession, *, runtime: EvidenceRuntime, authorized: AuthorizedWorkspace, data: bytes
) -> StoredObject:
    """Store ``data`` for this Workspace with the publication boundary held; it stays held."""
    planned_key = _planned_key(runtime, authorized, data)
    await lock_object_publication(db, project_id=authorized.project_id, object_key=planned_key)
    # Under the boundary: a retention hold means an operator pass owns this exact key, so
    # deferring is cheaper for both sides than writing bytes and then waiting for its pass.
    if await object_key_is_held(db, project_id=authorized.project_id, object_key=planned_key):
        logger.info(
            "Knowledge evidence ingestion deferred by a retention hold: workspace=%s",
            authorized.project_id,
        )
        raise EvidenceStoreUnavailableError()

    stored = await _store(runtime, authorized, data)
    if stored.ref.key != planned_key:
        # The boundary is only worth anything if it names the key that was written.
        raise EvidenceLedgerContractError()
    return stored


def _planned_key(runtime: EvidenceRuntime, authorized: AuthorizedWorkspace, data: bytes) -> str:
    """The content address the write will use, mapped to this slice's states.

    Hashes the payload a second time (the write hashes it too) on purpose: one derivation
    that cannot reach the wire is worth more than saving a SHA-256 over at most
    ``MAX_UPLOAD_BYTES``, and the alternative — locking the key the write reports — would
    leave the write itself outside the boundary.
    """
    failure: Exception | None = None
    try:
        return runtime.object_store.planned_key(authorized.workspace, data)
    except KnowledgeObjectNotConfiguredError:
        failure = EvidenceStoreNotConfiguredError()
    except KnowledgeObjectTooLargeError:
        failure = EvidencePayloadTooLargeError()
    except KnowledgeObjectError:
        failure = EvidenceStoreUnavailableError()
    # Raised outside the handler so no object-store error is chained as context.
    raise failure


async def _store(runtime: EvidenceRuntime, authorized: AuthorizedWorkspace, data: bytes) -> StoredObject:
    """Write-if-absent, mapping object-store failures to the slice's states."""
    failure: Exception | None = None
    try:
        return await runtime.object_store.put_if_absent(authorized.workspace, data)
    except KnowledgeObjectNotConfiguredError:
        failure = EvidenceStoreNotConfiguredError()
    except KnowledgeObjectTooLargeError:
        failure = EvidencePayloadTooLargeError()
    except KnowledgeObjectError:
        # Unavailable, unauthorized, integrity, and contract failures are all
        # "not right now" to a caller; none of their detail may be rendered.
        failure = EvidenceStoreUnavailableError()
    # Raised outside the handler so no object-store error is chained as context.
    raise failure


__all__ = ["publish_object"]
