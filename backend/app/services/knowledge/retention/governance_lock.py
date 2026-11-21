"""The cross-process serialization boundary of one Workspace's governance transitions.

Two writers change what a Workspace's retention record says, and they must not interleave:

- ``policy.set_retention_policy`` (including setting a legal hold, and including the *insert*
  of a first policy row, which no row lock could serialize);
- ``reconcile_record``, the transaction that supersedes earlier findings and publishes a new
  newest run.

Both take a transaction-scoped advisory lock on ``(namespace, project_id)`` before they read or
write, so a policy change and a superseding run of the same Workspace are applied one after
the other, across processes. The commit or rollback releases it.

Engine dependency, stated rather than hidden: advisory locks are a PostgreSQL facility. On an
engine that cannot hold them the boundary reports ``serialized=False`` and logs it; report-only
reconciliation and policy writes still work there.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..ledger.advisory_locks import advisory_lock_key, serializes_advisory_locks, take_transaction_lock
from .errors import InvalidRetentionRequestError

logger = logging.getLogger(__name__)

# Versioned and distinct from the object publication namespace, so the two boundaries are
# independent keys even for the same Workspace id.
GOVERNANCE_LOCK_NAMESPACE = "octryx.knowledge.retention.governance.v1"


@dataclass(frozen=True, slots=True)
class GovernanceLock:
    """What one governance lock attempt established for the rest of the transaction.

    ``serialized`` is True only when a transaction-scoped lock is really held. It is False on an
    engine without advisory locks, which is a recorded fact a caller must be able to surface —
    never a success.
    """

    project_id: str
    lock_key: int
    serialized: bool


def governance_lock_key(project_id: object) -> int:
    """The deterministic 64-bit advisory key of one Workspace's governance transitions.

    Deterministic, not collision-free: see ``services/knowledge/advisory_locks.py`` for why the
    boundary needs only the former, and why a collision is extra waiting rather than a hole.
    """
    if type(project_id) is not str or not project_id:
        raise InvalidRetentionRequestError()
    return advisory_lock_key(GOVERNANCE_LOCK_NAMESPACE, project_id)


async def lock_workspace_governance(db: AsyncSession, *, project_id: str) -> GovernanceLock:
    """Hold this Workspace's governance boundary for the rest of ``db``'s transaction.

    Blocks inside the database while another transaction — in this process or any other — is
    changing the policy or recording a superseding run of this Workspace. Released by that
    transaction's commit or rollback, so a crashed process cannot keep it.
    """
    lock_key = governance_lock_key(project_id)
    if not serializes_advisory_locks(db):
        # Recorded, never silent: the report-only paths continue unserialized.
        logger.warning(
            "Knowledge retention governance is not serialized on this engine: workspace=%s", project_id
        )
        return GovernanceLock(project_id=project_id, lock_key=lock_key, serialized=False)
    await take_transaction_lock(db, lock_key)
    return GovernanceLock(project_id=project_id, lock_key=lock_key, serialized=True)

