"""One bounded run of an ``embed_revision`` obligation.

The revision is current and its spans are already projected; this adds their vectors in the
Instance's embedding space. Admission comes first, because the span text is what may leave the
process for a remote space: a Workspace whose classification the space may not receive is
refused before any call. The run is bounded like projection (at most one provider batch and
``EMBED_SPANS_PER_RUN`` writes), holds the same lease, and continues from the persisted cursor.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..embedding.port import MAX_BATCH_TEXTS, EmbeddingError, EmbeddingPurpose, EmbeddingState
from ..embedding.selection import admit_space
from ..evidence_index.operations import set_vector_operation
from ..identity.workspace import WorkspaceId
from ..ledger.citations import load_spans
from ..ledger.errors import EvidenceLedgerContractError
from ..runtime import EvidenceRuntime
from .outbox_lease import ClaimedProjection
from .span_bodies import PURPOSE_EMBED, projected_span_texts
from .vector_spaces import record_vector_space

EMBED_SPANS_PER_RUN = MAX_BATCH_TEXTS


async def embed_revision_batch(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    workspace: WorkspaceId,
    claim: ClaimedProjection,
    hold_lease: Callable[[], Awaitable[bool]],
) -> tuple[int, int, bool]:
    """Embed the next spans after the cursor. Returns ``(embedded, last ordinal, more pending)``."""
    embedding = runtime.embedding
    if embedding is None:
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, runtime.embedding_unavailable_reason)
    await admit_space(db, project_id=claim.project_id, space=embedding.space)
    if not await runtime.runtime_client.vectors_available():
        # The index has no vector table (no pgvector on this server).
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "vector_index_unavailable")
    await record_vector_space(db, claim.project_id, embedding.space.key)

    cursor = claim.projected_through_ordinal
    spans = await load_spans(
        db, workspace.canonical, claim.revision_id, after_ordinal=cursor, limit=EMBED_SPANS_PER_RUN + 1
    )
    if not spans:
        # A current revision always has spans; the ledger and the outbox disagree.
        raise EvidenceLedgerContractError()
    batch = spans[:EMBED_SPANS_PER_RUN]
    if not await hold_lease():
        return 0, cursor, True
    # A code span is embedded with its file and symbol header; other spans as they are.
    texts = await projected_span_texts(db, workspace.canonical, claim.revision_id, batch, purpose=PURPOSE_EMBED)
    vectors = await embedding.embedder.embed(
        [texts[int(span.span_ordinal)] for span in batch], EmbeddingPurpose.DOCUMENT
    )
    operation = set_vector_operation(embedding.space.key)
    embedded, last_ordinal = 0, cursor
    for span, vector in zip(batch, vectors, strict=True):
        if not await hold_lease():
            return embedded, last_ordinal, True
        await runtime.runtime_client.run(workspace, operation, {"embedding": vector, "evidence_key": span.evidence_key})
        embedded += 1
        last_ordinal = int(span.span_ordinal)
    return embedded, last_ordinal, len(spans) > len(batch)


__all__ = ["EMBED_SPANS_PER_RUN", "embed_revision_batch"]
