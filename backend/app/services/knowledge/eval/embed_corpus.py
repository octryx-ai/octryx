"""Give an evaluation Workspace vectors in one embedding space, directly."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import REVISION_STATE_PROJECTED, KnowledgeSourceRevision
from ..access.authorization import AuthorizedWorkspace
from ..embedding.port import MAX_BATCH_TEXTS, EmbeddingPurpose
from ..embedding.selection import admit_space
from ..evidence_index.operations import set_vector_operation
from ..ledger.citations import load_spans
from ..projection.vector_spaces import record_vector_space
from ..runtime import EvidenceRuntime


async def embed_workspace(db: AsyncSession, *, runtime: EvidenceRuntime, authorized: AuthorizedWorkspace) -> int:
    embedding = runtime.embedding
    if embedding is None:
        raise ValueError("the evaluation runtime has no embedding space")
    await admit_space(db, project_id=authorized.project_id, space=embedding.space)
    if not await runtime.runtime_client.vectors_available():
        raise ValueError("the evidence index has no vector table (pgvector is not installed)")
    await record_vector_space(db, authorized.project_id, embedding.space.key)
    await db.commit()
    revisions = (
        (
            await db.execute(
                select(KnowledgeSourceRevision.id).where(
                    KnowledgeSourceRevision.project_id == authorized.project_id,
                    KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
                )
            )
        )
        .scalars()
        .all()
    )
    operation = set_vector_operation(embedding.space.key)
    embedded = 0
    for revision_id in revisions:
        cursor = 0
        while spans := await load_spans(
            db, authorized.project_id, revision_id, after_ordinal=cursor, limit=MAX_BATCH_TEXTS
        ):
            vectors = await embedding.embedder.embed([span.text for span in spans], EmbeddingPurpose.DOCUMENT)
            for span, vector in zip(spans, vectors, strict=True):
                await runtime.runtime_client.run(
                    authorized.workspace, operation, {"embedding": vector, "evidence_key": span.evidence_key}
                )
            embedded += len(spans)
            cursor = int(spans[-1].span_ordinal)
    return embedded


__all__ = ["embed_workspace"]
