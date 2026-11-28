"""Hybrid retrieval and the read tool: fused, floored, cited, and explicit when partial."""

from __future__ import annotations

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.embedding.port import EmbeddingRuntime
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.hybrid import hybrid_workspace_evidence
from app.services.knowledge.retrieval.lexical_recall import fetch_terms
from app.tools.knowledge_evidence.read import KnowledgeReadTool
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context
from tests.knowledge_evidence_text_support import ConceptEmbedder
from tests.knowledge_runtime_support import set_evidence_runtime

LOCAL = embedding_space("local_mlminilm_384_v1")
RUNBOOK = (
    "Scope of this runbook.\n\nThe failover exercise happens every Tuesday.\n\nEscalate to the platform on-call.\n"
)


async def _workspace(db, *, embedded: bool = True):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    embedding = EmbeddingRuntime(space=LOCAL, embedder=ConceptEmbedder(LOCAL)) if embedded else None
    runtime, _, evidence_index = build_runtime(embedding=embedding)
    return workspace_id, user_id, authorized, runtime


async def _ingest(db, runtime, authorized, user_id, key: str, text: str) -> None:
    await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=key,
        display_title=key,
        declared_media_type="text/markdown",
        data=text.encode(),
        created_by=user_id,
        source_url=f"https://docs.example.test/{key}",
    )
    projector = EvidenceProjector(runtime)
    while await projector.project_once(db, worker_id="test") is not None:
        pass


def test_function_words_no_longer_spend_the_lexical_fetch_budget() -> None:
    assert fetch_terms("When is the failover drill?") == ("failover", "drill")
    assert fetch_terms("the is") == ("the", "is")


async def test_hybrid_fuses_both_modes_and_keeps_a_floored_paraphrase(db) -> None:
    _, user_id, authorized, runtime = await _workspace(db)
    await _ingest(db, runtime, authorized, user_id, "runbook", RUNBOOK)
    await _ingest(db, runtime, authorized, user_id, "vault", "Passwords rotate every month.\n")

    result = await hybrid_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="failover drill")

    assert result.mode_states == {"lexical": "ok", "vector": "ok", "rerank": "needs_configuration"}
    top = result.evidence[0]
    assert top.evidence.text == "The failover exercise happens every Tuesday."
    assert set(top.modes) == {"lexical", "vector"}
    assert all("Passwords" not in hit.evidence.text for hit in result.evidence)
    paraphrase = await hybrid_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="rehearsal")
    assert [hit.modes for hit in paraphrase.evidence][:1] == [("vector",)]


async def test_without_vectors_the_answer_is_lexical_and_says_so(db) -> None:
    _, user_id, authorized, runtime = await _workspace(db, embedded=False)
    await _ingest(db, runtime, authorized, user_id, "runbook", RUNBOOK)

    result = await hybrid_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="failover drill")

    assert result.mode_states == {"lexical": "ok", "vector": "needs_configuration", "rerank": "needs_configuration"}
    assert [hit.modes for hit in result.evidence] == [("lexical",)]


async def test_the_tools_return_structured_citations_and_read_the_surrounding_paragraphs(db) -> None:
    workspace_id, user_id, authorized, runtime = await _workspace(db)
    await _ingest(db, runtime, authorized, user_id, "runbook", RUNBOOK)
    context = tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
    set_evidence_runtime(runtime)
    try:
        search = await KnowledgeSearchTool().execute({"query": "failover drill"}, context)
        hit = search["evidence"][0]
        read = await KnowledgeReadTool().execute({"evidence_key": hit["evidence_key"]}, context)
        refused = await KnowledgeReadTool().execute({"evidence_key": hit["evidence_key"], "window": 9}, context)
    finally:
        set_evidence_runtime(None)

    assert search["mode_states"] == {"lexical": "ok", "vector": "ok", "rerank": "needs_configuration"}
    assert hit["source_url"] == "https://docs.example.test/runbook"
    assert hit["revision"] == 1 and hit["chars"][1] > hit["chars"][0] and "lexical" in hit["found_by"]
    assert read["state"] == "ok" and read["current"] is True and read["spans"] == [1, 3]
    assert len(read["passage_keys"]) == 3 and read["passage_keys"][1] == read["evidence_key"]
    assert read["text"] == "\n\n".join(f"[{key}]\n{line}" for key, line in zip(read["passage_keys"], (
        "Scope of this runbook.", "The failover exercise happens every Tuesday.", "Escalate to the platform on-call.")))
    assert refused["state"] == "invalid_request"


async def test_a_key_of_another_workspace_reads_as_not_found(db) -> None:
    owner_id, owner_user, owner, runtime = await _workspace(db)
    await _ingest(db, runtime, owner, owner_user, "runbook", RUNBOOK)
    other_id, other_user, _, _ = await _workspace(db)
    owner_context = tool_context(user_id=owner_user, project_id=owner_id, project_ids=[owner_id], db=db)
    other_context = tool_context(user_id=other_user, project_id=other_id, project_ids=[other_id], db=db)
    set_evidence_runtime(runtime)
    try:
        key = (await KnowledgeSearchTool().execute({"query": "failover"}, owner_context))["evidence"][0][
            "evidence_key"
        ]
        foreign = await KnowledgeReadTool().execute({"evidence_key": key}, other_context)
    finally:
        set_evidence_runtime(None)
    assert foreign["state"] == "not_found"


class _FakeRerankClient:
    def __init__(self, *, relevant: str) -> None:
        self.relevant = relevant
        self.calls = 0

    def invoke_model(self, *, modelId: str, body: str, contentType: str, accept: str):  # noqa: N803 - boto3 casing
        import io
        import json

        self.calls += 1
        request = json.loads(body)
        results = [
            {"index": index, "relevance_score": 0.8 if self.relevant in document.lower() else 0.02}
            for index, document in enumerate(request["documents"])
        ]
        return {"body": io.BytesIO(json.dumps({"results": results}).encode())}


def _with_reranker(runtime, client):
    from dataclasses import replace

    from app.services.knowledge.rerank.bedrock import BedrockReranker
    from app.services.knowledge.rerank.catalog import reranker_spec
    from app.services.knowledge.rerank.selection import RerankerRuntime

    spec = reranker_spec("bedrock_cohere_rerank35_v1")
    return replace(runtime, reranker=RerankerRuntime(spec=spec, reranker=BedrockReranker(spec, client=client)))


async def _classify(db, workspace_id: str, classification: str) -> None:
    from sqlalchemy import update

    from app.models import Project

    await db.execute(
        update(Project)
        .where(Project.id == workspace_id)
        .values(config={"data_policy": {"classification": classification}})
    )
    await db.flush()


async def test_a_reranker_reorders_and_drops_what_is_not_evidence(db) -> None:
    workspace_id, user_id, authorized, runtime = await _workspace(db)
    await _ingest(db, runtime, authorized, user_id, "runbook", RUNBOOK)
    await _classify(db, workspace_id, "internal")
    client = _FakeRerankClient(relevant="tuesday")
    reranked = _with_reranker(runtime, client)

    result = await hybrid_workspace_evidence(db, runtime=reranked, authorized=authorized, query_text="failover runbook")

    assert result.mode_states["rerank"] == "ok" and client.calls == 1
    assert [hit.evidence.text for hit in result.evidence] == ["The failover exercise happens every Tuesday."]
    assert result.evidence[0].relevance == 0.8


async def test_an_unclassified_workspace_is_not_sent_to_the_reranker(db) -> None:
    _, user_id, authorized, runtime = await _workspace(db)
    await _ingest(db, runtime, authorized, user_id, "runbook", RUNBOOK)
    client = _FakeRerankClient(relevant="tuesday")

    result = await hybrid_workspace_evidence(
        db, runtime=_with_reranker(runtime, client), authorized=authorized, query_text="failover runbook"
    )

    assert result.mode_states["rerank"] == "needs_configuration" and client.calls == 0
    assert result.evidence and all(hit.relevance is None for hit in result.evidence)
    plain = await hybrid_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="failover runbook")
    assert plain.mode_states["rerank"] == "needs_configuration"
