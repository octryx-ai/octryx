"""Write an accepted upload's bytes under the publication boundary. Fixed order: ownership row, content address,
advisory lock, retention-hold check, write."""

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
    # Hashes the payload a second time on purpose: a derivation that cannot reach the wire is worth one more SHA-256.
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
