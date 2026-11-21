"""Runtime wiring of the Workspace Knowledge Evidence doubles: an ``EvidenceRuntime`` over the in-memory fakes."""

from __future__ import annotations

from app.services.knowledge.retrieval.index_query_store import EvidenceIndexQueryStore
from app.services.knowledge.runtime import EvidenceRuntime
from tests.knowledge_evidence_index_support import FakeEvidenceIndex
from tests.knowledge_evidence_s3_support import PREFIX, FakeS3Client, object_store


def build_runtime(
    *,
    s3: FakeS3Client | None = None,
    index: FakeEvidenceIndex | None = None,
    prefix: str | None = PREFIX,
    embedding=None,
) -> tuple[EvidenceRuntime, FakeS3Client, FakeEvidenceIndex]:
    """An ``EvidenceRuntime`` wired entirely to the in-memory doubles (``embedding``: an EmbeddingRuntime)."""
    s3 = s3 if s3 is not None else FakeS3Client()
    index = index if index is not None else FakeEvidenceIndex()
    runtime = EvidenceRuntime(
        object_store=object_store(s3, prefix=prefix),
        runtime_client=index,
        query_store=EvidenceIndexQueryStore(index, embedding=embedding),
        embedding=embedding,
    )
    return runtime, s3, index
