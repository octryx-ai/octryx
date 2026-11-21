"""The values one projector run reports: the run's newest claim, and its outcome.

``finished_outcome`` is the closing of a run that did not fail: it logs what happened and answers
the outcome, so ``projector`` keeps only the run itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_EMBED_REVISION,
    OUTBOX_OPERATION_RETIRE_REVISION,
    OUTBOX_STATE_APPLIED,
)
from ..ledger.errors import EvidenceLedgerContractError
from .outbox_lease import LEASE_LOST, ClaimedProjection

# Logged under the projector's name, so the split leaves log routing unchanged.
logger = logging.getLogger(__package__ + ".projector")


@dataclass(slots=True)
class _RunLease:
    """The newest claim value of one bounded run.

    The claim itself stays immutable: renewal answers a *new* frozen
    :class:`ClaimedProjection`, and this holder is only what keeps the newest one
    reachable after the batch returns or raises, so the closing transition is always
    compared against the deadline the row actually carries.
    """

    claim: ClaimedProjection
    # Set when a renewal was refused: the run stops and reports lease loss instead
    # of spending further dependency calls on an obligation it no longer owns.
    lost: bool = False


@dataclass(frozen=True, slots=True)
class ProjectionOutcome:
    """Result of one projector turn.

    ``spans_projected`` counts this run only. ``more_spans_pending`` is True when the
    bounded run stopped before the last span; the obligation is then still pending and
    ``applied`` is False. It is deliberately a flag and not a remaining count: the run
    reads one row past its bound to learn that more work exists, and does not count
    the rest.

    ``deferred`` is True when a parse run is still waiting for the parser sandbox. It is
    not a failure: ``failure`` stays ``None`` and the attempt count is untouched.
    """

    revision_id: str
    project_id: str
    spans_projected: int
    applied: bool
    failure: str | None
    outbox_state: str | None
    more_spans_pending: bool = False
    deferred: bool = False



def projection_outcome(
    claimed: ClaimedProjection,
    projected: int,
    outbox_state: str,
    *,
    failure: str | None = None,
    more_pending: bool = False,
    deferred: bool = False,
) -> ProjectionOutcome:
    return ProjectionOutcome(
        revision_id=claimed.revision_id,
        project_id=claimed.project_id,
        spans_projected=projected,
        # Only a completed, still-owned run counts as applied.
        applied=failure is None and not more_pending and outbox_state == OUTBOX_STATE_APPLIED,
        failure=failure,
        outbox_state=outbox_state,
        more_spans_pending=more_pending,
        deferred=deferred,
    )


def finished_outcome(
    current: ClaimedProjection, projected: int, outbox_state: str | None, *, more_pending: bool
) -> ProjectionOutcome:
    """Log and answer the outcome of a run that transitioned its entry without failing."""
    if outbox_state is None:  # pragma: no cover - every success transitions once
        raise EvidenceLedgerContractError()
    if more_pending and outbox_state != LEASE_LOST:
        # Bounded run: the cursor advances, the obligation stays pending, and the
        # revision is *not* marked projected.
        return projection_outcome(current, projected, outbox_state, more_pending=True)
    if outbox_state == LEASE_LOST:
        # The spans were written idempotently, but this run no longer owns the
        # obligation, so it must not report the revision as projected.
        logger.warning("Knowledge projection ended without its lease: workspace=%s", current.project_id)
    else:
        logger.info(
            "Knowledge evidence revision %s: spans=%d workspace=%s",
            {OUTBOX_OPERATION_RETIRE_REVISION: "retired", OUTBOX_OPERATION_EMBED_REVISION: "embedded"}.get(
                current.operation, "projected"
            ),
            projected,
            current.project_id,
        )
    return projection_outcome(current, projected, outbox_state)
