"""The outbox projector: applies one revision's spans to the Workspace Evidence index.

Idempotent by construction. Each span is written with the registry's upsert by
``evidence_key``, so re-running a claimed entry, or re-projecting a revision
after a rebuild, converges instead of duplicating or erroring. The index schema
comes from the Alembic migration, so a run issues no DDL.

Failures never carry text. Every dependency error is mapped to one of the fixed
``ALL_PROJECTION_FAILURES`` tokens before it touches the database, so a driver
message — which may carry statement text and values — can never be persisted,
logged, or returned.

Bounded per run, continued from a cursor. One span is one upsert call, so
a revision may owe up to ``spans.MAX_SPANS_PER_REVISION`` calls — far too many to
run inside one synchronous HTTP request. A run therefore applies at most
:data:`MAX_SPANS_PER_RUN` ordinals, persists how far it got in the outbox entry's
``projected_through_ordinal``, and leaves the obligation ``pending`` and due.
Partial work is never marked applied; only the run that projects the last span
does that.

Lease ownership decides the outcome. Every transition requires this run to still
hold the exact claim generation it started with; a reclaimed or expired lease
answers ``lease_lost`` and reports ``applied=False`` rather than overwriting the
new holder's state. The upserts themselves are idempotent, so nothing is corrupted
by the overlap. A run whose remaining lease drops below
:data:`LEASE_RENEWAL_MARGIN_SECONDS` renews it and continues with the new claim
value, so the bound on one run is the run budget below — not an unwritten
assumption that the budget happens to be shorter than the lease.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_EMBED_REVISION,
    OUTBOX_OPERATION_EXTRACT_GRAPH,
    OUTBOX_OPERATION_PARSE_REVISION,
)
from ....time_utils import utc_now
from ..access.authorization import parse_workspace_id
from ..identity.workspace import WorkspaceId
from ..ledger.errors import EvidenceLedgerContractError
from ..runtime import EvidenceRuntime
from .embedding_step import embed_revision_batch
from .failures import failure_token
from .outbox import claim_next, mark_failed, renew_lease
from .outbox_lease import DEFAULT_LEASE_SECONDS, LEASE_LOST, ClaimedProjection
from .outbox_transitions import mark_applied, mark_contended, mark_progress
from .parse_step import PARSE_POLL_SECONDS, parse_revision_step
from .projector_outcome import ProjectionOutcome, _RunLease, finished_outcome, projection_outcome
from .projector_spans import project_span_batch

logger = logging.getLogger(__name__)

# One span is one upsert call: the per-run bound is what keeps a large revision
# from turning one authorized request into thousands of sequential calls.
MAX_SPANS_PER_RUN = 100
# The wall-clock budget of one run. It bounds how long an authorized request can
# block on slow dependency calls; lease ownership is held by renewal, not by this
# value staying below the lease.
PROJECTION_RUN_TIMEOUT_SECONDS = 90
# Renew once the remaining lease falls to half the default lease. Renewal installs
# a full default lease again, so the margin is crossed at most once per lease
# period and a run cannot turn into one database write per span.
LEASE_RENEWAL_MARGIN_SECONDS = DEFAULT_LEASE_SECONDS // 2
# A graph extraction run renews its claim for its own, longer budget (temporal/extraction_step.py).
GRAPH_RUN_TIMEOUT_SECONDS = 360


def _run_budget(operation: str) -> int:
    return GRAPH_RUN_TIMEOUT_SECONDS if operation == OUTBOX_OPERATION_EXTRACT_GRAPH else PROJECTION_RUN_TIMEOUT_SECONDS


class EvidenceProjector:
    """Applies claimed projection obligations with the non-root credential."""

    def __init__(self, runtime: EvidenceRuntime) -> None:
        if type(runtime) is not EvidenceRuntime:
            raise EvidenceLedgerContractError()
        self._runtime = runtime

    async def project_once(
        self, db: AsyncSession, *, worker_id: str, project_id: str | None = None
    ) -> ProjectionOutcome | None:
        """Claim and apply one due entry, or return ``None`` when nothing is due."""
        claimed = await claim_next(db, worker_id=worker_id, project_id=project_id)
        if claimed is None:
            return None
        return await self.apply_claimed(db, claimed)

    async def apply_claimed(self, db: AsyncSession, claimed: ClaimedProjection) -> ProjectionOutcome:
        """Apply one bounded batch of a leased entry; a failure is recorded, never raised."""
        if type(claimed) is not ClaimedProjection:
            raise EvidenceLedgerContractError()
        if claimed.operation == OUTBOX_OPERATION_PARSE_REVISION:
            return await self._apply_parse(db, claimed)
        workspace = parse_workspace_id(claimed.project_id)
        lease = _RunLease(claimed)
        failure: str | None = None
        projected = 0
        last_ordinal = claimed.projected_through_ordinal
        more_pending = False
        outbox_state: str | None = None
        try:
            async with asyncio.timeout(_run_budget(claimed.operation)):
                projected, last_ordinal, more_pending = await self._project_batch(db, workspace, lease)
            outbox_state = await self._close_run(db, lease, last_ordinal, more_pending=more_pending)
        # Every dependency failure is deliberately reduced to a fixed token.
        except Exception as error:
            failure = failure_token(error)
        # Renewal replaced the claim value; the closing transitions must use the
        # newest one, or they would be refused as a stale generation.
        current = lease.claim
        if failure is not None:
            return self._outcome(current, 0, await mark_failed(db, current, failure), failure=failure)
        return finished_outcome(current, projected, outbox_state, more_pending=more_pending)

    async def _close_run(
        self, db: AsyncSession, lease: _RunLease, last_ordinal: int, *, more_pending: bool
    ) -> str:
        """The one transition a run that did not fail makes; ``lease_lost`` when its renewal was refused."""
        if lease.lost:
            # The renewal that would have kept this run's claim alive was
            # refused, so no transition is attempted at all.
            return LEASE_LOST
        if more_pending:
            return await mark_progress(db, lease.claim, last_ordinal)
        return await mark_applied(db, lease.claim, embed_current=self._runtime.embedding is not None)

    async def _apply_parse(self, db: AsyncSession, claimed: ClaimedProjection) -> ProjectionOutcome:
        """One bounded run of a parse obligation: submit, poll, or write the parsed spans.

        Waiting for the sandbox is reported like a deferral (no attempt spent). A failure rolls
        back whatever the run added before the attempt is recorded, so a half-written parse is
        never committed.
        """
        lease = _RunLease(claimed)
        try:
            async with asyncio.timeout(PROJECTION_RUN_TIMEOUT_SECONDS):
                parsed = await parse_revision_step(
                    db,
                    runtime=self._runtime,
                    workspace=parse_workspace_id(claimed.project_id),
                    claim=claimed,
                    hold_lease=lambda: self._hold_lease(db, lease),
                )
            if lease.lost:
                return self._outcome(lease.claim, 0, LEASE_LOST)
            if parsed is None:
                state = await mark_contended(db, lease.claim, retry_after_seconds=PARSE_POLL_SECONDS)
                return self._outcome(lease.claim, 0, state, deferred=True)
            state = await mark_applied(db, lease.claim)
        except Exception as error:
            failure = failure_token(error)
            await db.rollback()
            return self._outcome(lease.claim, 0, await mark_failed(db, lease.claim, failure), failure=failure)
        if state != LEASE_LOST:
            logger.info("Knowledge evidence revision parsed: spans=%d workspace=%s", parsed, claimed.project_id)
        return self._outcome(lease.claim, parsed, state)

    _outcome = staticmethod(projection_outcome)

    async def _project_batch(self, db: AsyncSession, workspace: WorkspaceId, lease: _RunLease) -> tuple[int, int, bool]:
        """Run one bounded step of the claimed obligation after the cursor.

        Returns ``(written, last ordinal, more pending)``. The lease is renewed before a span
        whenever it is close to expiry, and ``lease.lost`` stops the run when that is refused.
        """
        if lease.claim.operation == OUTBOX_OPERATION_EXTRACT_GRAPH:
            from ..temporal.extraction_step import EPISODE_LEASE_SECONDS, extract_graph_step

            return await extract_graph_step(
                db,
                runtime=self._runtime,
                claim=lease.claim,
                hold_lease=lambda: self._renew_for(db, lease, EPISODE_LEASE_SECONDS),
            )
        if lease.claim.operation == OUTBOX_OPERATION_EMBED_REVISION:
            return await embed_revision_batch(
                db,
                runtime=self._runtime,
                workspace=workspace,
                claim=lease.claim,
                hold_lease=lambda: self._hold_lease(db, lease),
            )
        return await project_span_batch(
            db,
            self._runtime,
            workspace,
            lease.claim,
            hold_lease=lambda: self._hold_lease(db, lease),
            max_spans=MAX_SPANS_PER_RUN,
        )

    @staticmethod
    async def _renew_for(db: AsyncSession, lease: _RunLease, seconds: int) -> bool:
        """Extend this run's claim to ``seconds`` from now, for a step with its own budget."""
        renewed = await renew_lease(db, lease.claim, lease_seconds=seconds)
        if type(renewed) is not ClaimedProjection:
            lease.lost = True
            return False
        lease.claim = renewed
        return True

    @staticmethod
    async def _hold_lease(db: AsyncSession, lease: _RunLease) -> bool:
        """Keep this run's claim alive, renewing it shortly before it would expire.

        Returns False once the claim is gone, which is the only case in which a
        bounded run stops before its batch: continuing would spend dependency calls
        on an obligation another claim generation already owns.
        """
        remaining = (lease.claim.lease_until - utc_now()).total_seconds()
        if remaining > LEASE_RENEWAL_MARGIN_SECONDS:
            return True
        renewed = await renew_lease(db, lease.claim)
        if type(renewed) is not ClaimedProjection:
            lease.lost = True
            logger.warning(
                "Knowledge projection lease could not be renewed mid-run: workspace=%s", lease.claim.project_id
            )
            return False
        lease.claim = renewed
        return True


__all__ = [
    "GRAPH_RUN_TIMEOUT_SECONDS",
    "LEASE_RENEWAL_MARGIN_SECONDS",
    "MAX_SPANS_PER_RUN",
    "PROJECTION_RUN_TIMEOUT_SECONDS",
    "EvidenceProjector",
]
