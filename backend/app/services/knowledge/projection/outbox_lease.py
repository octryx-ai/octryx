"""The outbox lease: its constants, the claim value, and the owned-transition fence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import OUTBOX_STATE_CLAIMED, KnowledgeProjectionOutboxEntry
from ....time_utils import utc_now
from ..ledger.errors import EvidenceLedgerContractError

# Logged under the outbox's name: one log route for the whole lease.
logger = logging.getLogger(__package__ + ".outbox")

DEFAULT_LEASE_SECONDS = 120
MAX_LEASE_SECONDS = 3600
RETRY_BACKOFF_SECONDS = (30, 120, 600, 3600)
MAX_CLAIMED_BY_CHARS = 64
# Contention is not a failure: its deferral has its own short budget, not the retry backoff.
DEFAULT_CONTENTION_DEFER_SECONDS = 15
MAX_CONTENTION_DEFER_SECONDS = 300

# Not an outbox column value: the answer to "this worker no longer holds the lease".
LEASE_LOST = "lease_lost"


@dataclass(frozen=True, slots=True)
class ClaimedProjection:

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
    # A lost lease can never be reported as a completed transition.
    if type(claimed) is not ClaimedProjection:
        raise EvidenceLedgerContractError()
    now = utc_now()
    result = await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(
            KnowledgeProjectionOutboxEntry.id == claimed.entry_id,
            KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_CLAIMED,
            KnowledgeProjectionOutboxEntry.claimed_by == claimed.claimed_by,
            # The generation token: worker identity is not unique per claim (``api:<user_id>``),
            # the exact installed deadline is.
            KnowledgeProjectionOutboxEntry.claimed_until == claimed.lease_until,
            # Expiry itself ends ownership, even before another worker reclaims the row.
            KnowledgeProjectionOutboxEntry.claimed_until > now,
        )
        .values(**values)
    )
    if result.rowcount != 1:
        # Reclaimed after expiry: discard this write rather than overwrite the new holder's state.
        await db.rollback()
        logger.warning(
            "Knowledge projection lease was lost before the transition: workspace=%s",
            claimed.project_id,
        )
        return False
    return True
