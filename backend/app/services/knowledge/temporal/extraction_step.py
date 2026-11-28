"""One bounded run of an ``extract_graph`` obligation: a batch of spans into the Workspace graph."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.outbox_lease import ClaimedProjection

from ....models.project.knowledge_evidence import REVISION_STATE_PROJECTED
from ..embedding.selection import admit_space
from ..ledger.citations import load_revision_scope
from ..runtime import EvidenceRuntime
from .errors import GraphNotConfiguredError
from .extraction_gaps import unextracted_spans
from .extraction_profiles import select_profile
from .extraction_step_reads import _revision_of
from .graphiti_llm import governed_graph_llm
from .postgres_extraction import extract_batch
from .postgres_extraction_model import SPANS_PER_CALL, SpanInput

# One batch can take several model calls, so an extraction run gets its own budget. The run renews
# its claim to EPISODE_LEASE_SECONDS before the batch, and the timeouts nest strictly: batch < run
# (``projection/projector.GRAPH_RUN_TIMEOUT_SECONDS``) < lease.
EPISODE_TIMEOUT_SECONDS = 300
EPISODE_LEASE_SECONDS = 420
DEFAULT_GROUP = "workspace"


async def extract_graph_step(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    claim: ClaimedProjection,
    hold_lease: Callable[[], Awaitable[bool]],
) -> tuple[int, int, bool]:
    if runtime.embedding is None:
        raise GraphNotConfiguredError()
    revision = await _revision_of(db, claim)
    cursor = claim.projected_through_ordinal
    if revision[0] != REVISION_STATE_PROJECTED:
        return 0, cursor, False
    products, version = await load_revision_scope(db, claim.project_id, claim.revision_id)
    group = products[0] if products else DEFAULT_GROUP
    # The data-defined profile that applies (``extraction_profiles``): a versioned document is
    # extracted as typed change records of its product and version.
    extraction = select_profile(tuple(products), version)
    title = revision[3] if not version else f"{revision[3]} (version {version})"
    return await _extract_on_postgres(
        db, runtime=runtime, claim=claim, extraction=extraction, group=group, version=version, title=title,
        valid_at=revision[1], hold_lease=hold_lease,
    )


async def _extract_on_postgres(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    claim: ClaimedProjection,
    extraction,
    group: str,
    version: str | None,
    title: str,
    valid_at,
    hold_lease: Callable[[], Awaitable[bool]],
) -> tuple[int, int, bool]:
    cursor = claim.projected_through_ordinal
    spans = await unextracted_spans(
        db, claim.project_id, claim.revision_id, extraction.profile_id, limit=SPANS_PER_CALL + 1
    )
    if not spans:
        return 0, cursor, False
    batch = spans[:SPANS_PER_CALL]
    embedding = runtime.embedding
    await admit_space(db, project_id=claim.project_id, space=embedding.space)
    llm = await governed_graph_llm(
        db,
        project_id=claim.project_id,
        check_change_edges=False,
        change_types=frozenset(extraction.edge_types or ()),
    )
    if not await hold_lease():
        return 0, cursor, True
    try:
        async with asyncio.timeout(EPISODE_TIMEOUT_SECONDS):
            await extract_batch(
                db, llm=llm, embedding=embedding, profile=extraction, project_id=claim.project_id,
                revision_id=claim.revision_id, group=group, version=version, title=title, valid_at=valid_at,
                spans=[SpanInput(int(span.span_ordinal), span.text) for span in batch],
            )
    except BaseException:
        # The failure transition commits; a half-written batch must not commit with it.
        await db.rollback()
        raise
    return len(batch), int(batch[-1].span_ordinal), len(spans) > len(batch)


__all__ = [
    "DEFAULT_GROUP",
    "EPISODE_LEASE_SECONDS",
    "EPISODE_TIMEOUT_SECONDS",
    "extract_graph_step",
]
