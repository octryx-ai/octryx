"""The span step of a projector run: upsert (or retire) a bounded batch after the cursor. Every span is preceded by the
lease check."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import OUTBOX_OPERATION_RETIRE_REVISION
from ..access.source_acl import span_marker_for_revision
from ..evidence_index.operations import DELETE_EVIDENCE, UPSERT_EVIDENCE_SCOPED
from ..identity.workspace import WorkspaceId
from ..ledger.citations import load_revision_scope, load_spans
from ..ledger.errors import EvidenceLedgerContractError
from ..runtime import EvidenceRuntime
from .acl_marker import converge_acl_marker
from .outbox_lease import ClaimedProjection
from .span_bodies import PURPOSE_INDEX, projected_span_texts


async def project_span_batch(
    db: AsyncSession,
    runtime: EvidenceRuntime,
    workspace: WorkspaceId,
    claim: ClaimedProjection,
    *,
    hold_lease: Callable[[], Awaitable[bool]],
    max_spans: int,
) -> tuple[int, int, bool]:
    cursor = claim.projected_through_ordinal
    # One row over the bound: enough to know more work is owed, without reading it.
    spans = await load_spans(db, workspace.canonical, claim.revision_id, after_ordinal=cursor, limit=max_spans + 1)
    if not spans:
        # A committed revision always has spans; an empty set means the ledger
        # and the outbox disagree, which must not be reported as success.
        raise EvidenceLedgerContractError()
    batch = spans[:max_spans]
    projected = 0
    last_ordinal = cursor
    retiring = claim.operation == OUTBOX_OPERATION_RETIRE_REVISION
    scope = ((), "", (), {})
    if not retiring:
        scope = await _span_scope(db, runtime, workspace, claim.revision_id, batch)
    for span in batch:
        if not await hold_lease():
            return projected, last_ordinal, True
        await _write_span(runtime, workspace, span, retiring=retiring, scope=scope)
        projected += 1
        last_ordinal = int(span.span_ordinal)
    return projected, last_ordinal, len(spans) > len(batch)


async def _span_scope(
    db: AsyncSession, runtime: EvidenceRuntime, workspace: WorkspaceId, revision_id: str, batch: list
) -> tuple:
    # Every projected span carries its revision's product and version scope
    # and its source's ACL marker, read per batch from the ledger.
    await converge_acl_marker(db, runtime.runtime_client, workspace)
    products, version = await load_revision_scope(db, workspace.canonical, revision_id)
    acl_keys = await span_marker_for_revision(db, workspace.canonical, revision_id)
    # A code span is indexed by its retrieval text (path, symbol, identifier words).
    bodies = await projected_span_texts(db, workspace.canonical, revision_id, batch, purpose=PURPOSE_INDEX)
    return products, version, acl_keys, bodies


async def _write_span(runtime: EvidenceRuntime, workspace: WorkspaceId, span, *, retiring: bool, scope: tuple) -> None:
    if retiring:
        # Idempotent: a span that is already gone answers ``count`` 0.
        await runtime.runtime_client.run(workspace, DELETE_EVIDENCE, {"evidence_key": span.evidence_key})
        return
    products, version, acl_keys, bodies = scope
    await runtime.runtime_client.run(
        workspace,
        UPSERT_EVIDENCE_SCOPED,
        {
            "evidence_key": span.evidence_key,
            "body_text": bodies[int(span.span_ordinal)],
            "revision_id": span.revision_id,
            "span_ordinal": int(span.span_ordinal),
            "products": list(products),
            "version": version,
            "acl_keys": list(acl_keys),
        },
    )
