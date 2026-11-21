"""The outbox lease: its constants, the claim value, and the owned-transition fence.

Shared by the claim path (``outbox``) and the closing transitions (``outbox_transitions``);
see ``outbox`` for why the exact installed deadline is the ownership token.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import OUTBOX_STATE_CLAIMED, KnowledgeProjectionOutboxEntry
from ....time_utils import utc_now
from ..ledger.errors import EvidenceLedgerContractError

# Logged under the outbox's name, so the split leaves log routing unchanged.
logger = logging.getLogger(__package__ + ".outbox")

DEFAULT_LEASE_SECONDS = 120
MAX_LEASE_SECONDS = 3600
RETRY_BACKOFF_SECONDS = (30, 120, 600, 3600)
MAX_CLAIMED_BY_CHARS = 64
# Contention is not a failure, so the deferral is bounded by its own budget rather
# than by the retry backoff: long enough not to hot-loop on the resource that is
# busy, short enough that a Workspace is not parked for minutes.
DEFAULT_CONTENTION_DEFER_SECONDS = 15
MAX_CONTENTION_DEFER_SECONDS = 300

# Not an outbox column value: the answer to "this worker no longer holds the lease".
LEASE_LOST = "lease_lost"


@dataclass(frozen=True, slots=True)
class ClaimedProjection:
    """One leased projection obligation, identified by Workspace and revision.

    ``claimed_by`` is the lease identity and ``lease_until`` is the **exact**
    deadline this claim installed: together they are the compare-and-set token of
    one claim generation, so a stale claim cannot transition a newer one even when
    both carry the same worker id. ``projected_through_ordinal`` is the persisted
    cursor a bounded projection run continues from.

    The value is immutable. :func:`renew_lease` answers with a new value carrying
    the advanced deadline, and the previous value stops being usable at that point.
    """

    entry_id: str
    project_id: str
    revision_id: str
    operation: str
    attempt_count: int
    max_attempts: int
    claimed_by: str
    projected_through_ordinal: int
    lease_until: datetime


def _backoff_seconds(attempt_count: int) -> int:
    index = min(max(attempt_count, 1), len(RETRY_BACKOFF_SECONDS)) - 1
    return RETRY_BACKOFF_SECONDS[index]


async def _owned_transition(db: AsyncSession, claimed: ClaimedProjection, values: dict[str, object]) -> bool:
    """Apply one transition only while this worker still holds *this* claim.

    Returns ``False`` without committing when the row no longer carries this exact
    claim generation, so a lost lease can never be reported as a completed
    transition.
    """
    if type(claimed) is not ClaimedProjection:
        raise EvidenceLedgerContractError()
    now = utc_now()
    result = await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(
            KnowledgeProjectionOutboxEntry.id == claimed.entry_id,
            KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_CLAIMED,
            KnowledgeProjectionOutboxEntry.claimed_by == claimed.claimed_by,
            # The generation token. Worker identity is not unique per claim (the
            # manual trigger reuses ``api:<user_id>``), so without the exact
            # installed deadline a stale run could transition the row a newer
            # claim of the same identity now owns.
            KnowledgeProjectionOutboxEntry.claimed_until == claimed.lease_until,
            # Expiry itself ends ownership. A slow worker must not transition an
            # obligation merely because no replacement worker has reclaimed it yet.
            KnowledgeProjectionOutboxEntry.claimed_until > now,
        )
        .values(**values)
    )
    if result.rowcount != 1:
        # Reclaimed by another projector after the lease expired: discard this
        # worker's intended write rather than overwriting the new holder's state.
        await db.rollback()
        logger.warning(
            "Knowledge projection lease was lost before the transition: workspace=%s",
            claimed.project_id,
        )
        return False
    return True
