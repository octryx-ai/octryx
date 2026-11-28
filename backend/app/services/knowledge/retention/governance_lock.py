"""The cross-process serialization boundary of one Workspace's governance transitions. Other engines report
``serialized=False``."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..ledger.advisory_locks import advisory_lock_key, serializes_advisory_locks, take_transaction_lock
from .errors import InvalidRetentionRequestError

logger = logging.getLogger(__name__)

# The namespace separates the lock purposes; a 64-bit hash collision with another purpose only adds serialization.
GOVERNANCE_LOCK_NAMESPACE = "octryx.knowledge.retention.governance.v1"


@dataclass(frozen=True, slots=True)
class GovernanceLock:
    # ``serialized`` False (no advisory locks) is a fact a caller must surface, never a success.
    project_id: str
    lock_key: int
    serialized: bool


def governance_lock_key(project_id: object) -> int:
    if type(project_id) is not str or not project_id:
        raise InvalidRetentionRequestError()
    return advisory_lock_key(GOVERNANCE_LOCK_NAMESPACE, project_id)


async def lock_workspace_governance(db: AsyncSession, *, project_id: str) -> GovernanceLock:
    # Serializes every policy change, first inserts included; released at commit or rollback, so a crash cannot keep it.
    lock_key = governance_lock_key(project_id)
    if not serializes_advisory_locks(db):
        # Recorded, never silent: the report-only paths continue unserialized.
        logger.warning(
            "Knowledge retention governance is not serialized on this engine: workspace=%s", project_id
        )
        return GovernanceLock(project_id=project_id, lock_key=lock_key, serialized=False)
    await take_transaction_lock(db, lock_key)
    return GovernanceLock(project_id=project_id, lock_key=lock_key, serialized=True)

